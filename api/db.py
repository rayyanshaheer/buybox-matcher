"""Supabase client construction and typed query helpers (design: ``api/db.py``).

This module owns persistence for the four core tables — ``buyers``,
``buy_boxes``, ``properties`` and ``matches`` — and exposes a small,
explicitly-typed set of insert/select helpers consumed by the API and seed
script (downstream tasks 5.4, 6.2, 7.1, 8.1).

Two design constraints shape this module:

1. **Lazy / injectable client (testability).** The Supabase SDK is imported
   *inside* :func:`get_client` only, and the client is built lazily from
   :class:`api.config.Settings`. Importing this module therefore never requires
   the ``supabase`` package to be installed nor live ``SUPABASE_URL`` /
   ``SUPABASE_KEY`` credentials. Every helper accepts an optional ``client``
   argument so unit tests can inject a fake, and :func:`set_client` allows a
   process-wide override.

2. **Explicit persistence errors (Req 9.5, 9.7, 9.8).** Enum-check violations,
   the one-to-one ``buyer_id`` uniqueness violation, and unresolved foreign-key
   references are surfaced as :class:`DbError` subclasses and **nothing is
   persisted**. Enum values are additionally validated in-process *before* any
   write so an invalid value is rejected deterministically (and without a live
   database); the database ``check`` constraints remain as defense in depth.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from api.config import Settings, load_settings, validate_config

# --------------------------------------------------------------------------- #
# Enum vocabularies (Req 9.5) — mirror the DDL check constraints.
# --------------------------------------------------------------------------- #

VALID_STRATEGIES: frozenset[str] = frozenset(
    {"fix_and_flip", "buy_and_hold", "brrrr", "wholesale"}
)
VALID_PROPERTY_TYPES: frozenset[str] = frozenset(
    {"single_family", "multi_family", "condo", "land"}
)
VALID_CONDITIONS: frozenset[str] = frozenset(
    {"distressed", "light_rehab", "turnkey", "any"}
)

# Table names (single source of truth).
BUYERS_TABLE = "buyers"
BUY_BOXES_TABLE = "buy_boxes"
PROPERTIES_TABLE = "properties"
MATCHES_TABLE = "matches"

# Postgres SQLSTATE codes surfaced by PostgREST on constraint violations.
_PG_UNIQUE_VIOLATION = "23505"
_PG_FK_VIOLATION = "23503"
_PG_CHECK_VIOLATION = "23514"


# --------------------------------------------------------------------------- #
# Explicit persistence errors (Req 9.5, 9.7, 9.8)
# --------------------------------------------------------------------------- #


class DbError(RuntimeError):
    """Base class for persistence failures surfaced by this module.

    Raised when a record is rejected and **not persisted**. The message
    describes the violation; it never includes credentials.
    """


class EnumViolationError(DbError):
    """An enum value is not a member of its defined vocabulary (Req 9.5)."""


class UniqueViolationError(DbError):
    """A one-to-one association is violated, e.g. a buyer already has a
    buy_box (Req 9.7)."""


class ForeignKeyViolationError(DbError):
    """A referenced Property or Buyer does not exist (Req 9.8)."""


# --------------------------------------------------------------------------- #
# Lazy / injectable Supabase client
# --------------------------------------------------------------------------- #

#: Process-wide client cache. Populated lazily by :func:`get_client` or
#: overridden by :func:`set_client` (e.g. in tests). Never built at import time.
_client: Any | None = None


def get_client(settings: Settings | None = None) -> Any:
    """Return the shared Supabase client, constructing it lazily on first use.

    The ``supabase`` SDK is imported here — not at module import — so importing
    :mod:`api.db` has no third-party dependency and cannot crash when the SDK
    or credentials are absent. Credentials are validated via
    :func:`api.config.validate_config` before the client is built (Req 14.4).

    Pass ``settings`` to build from an explicit configuration; otherwise the
    environment is read via :func:`api.config.load_settings`.
    """
    global _client
    if _client is not None:
        return _client

    resolved = validate_config(settings if settings is not None else load_settings())

    try:
        from supabase import create_client  # imported lazily on purpose
    except ImportError as exc:  # pragma: no cover - depends on install env
        raise DbError(
            "The 'supabase' package is required to construct the database "
            "client but is not installed."
        ) from exc

    # validate_config guarantees these are present and non-empty.
    _client = create_client(resolved.supabase_url, resolved.supabase_key)
    return _client


def set_client(client: Any) -> None:
    """Override the shared client (used for dependency injection / tests)."""
    global _client
    _client = client


def reset_client() -> None:
    """Clear the cached client so the next :func:`get_client` rebuilds it."""
    global _client
    _client = None


def _resolve_client(client: Any | None) -> Any:
    """Return the explicit ``client`` if given, else the shared lazy client."""
    return client if client is not None else get_client()


# --------------------------------------------------------------------------- #
# Error translation
# --------------------------------------------------------------------------- #


def _translate_db_exception(exc: Exception) -> DbError | None:
    """Map a PostgREST/Postgres exception to a :class:`DbError`, or ``None``.

    Classification prefers the Postgres SQLSTATE ``code`` exposed by PostgREST's
    ``APIError`` and falls back to message-text matching so the mapping is
    robust across client versions.
    """
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None) or str(exc)
    haystack = message.lower()

    if code == _PG_UNIQUE_VIOLATION or "duplicate key" in haystack or (
        "unique" in haystack and "violat" in haystack
    ):
        return UniqueViolationError(
            "buyer already has an associated buy_box (one-to-one violation)"
        )
    if code == _PG_FK_VIOLATION or "foreign key" in haystack:
        return ForeignKeyViolationError(
            "referenced property or buyer does not exist"
        )
    if code == _PG_CHECK_VIOLATION or "check constraint" in haystack:
        return EnumViolationError(
            "a submitted value violates a database check constraint"
        )
    return None


def _execute(query: Any) -> list[dict]:
    """Run a built PostgREST query, translating constraint errors.

    Returns the response ``data`` as a list of row dicts. Any recognised
    constraint violation is re-raised as the matching :class:`DbError`;
    unrecognised errors propagate unchanged.
    """
    try:
        response = query.execute()
    except Exception as exc:  # noqa: BLE001 - re-raised below, translated or as-is
        translated = _translate_db_exception(exc)
        if translated is not None:
            raise translated from exc
        raise

    data = getattr(response, "data", None)
    if data is None:
        return []
    if isinstance(data, dict):
        return [data]
    return list(data)


# --------------------------------------------------------------------------- #
# In-process enum validation (Req 9.5)
# --------------------------------------------------------------------------- #


def _check_enum(value: str | None, allowed: frozenset[str], field_name: str) -> None:
    """Raise :class:`EnumViolationError` if a non-null ``value`` is invalid."""
    if value is not None and value not in allowed:
        raise EnumViolationError(
            f"invalid {field_name} value; expected one of: "
            + ", ".join(sorted(allowed))
        )


def _validate_buy_box_enums(buy_box: Mapping[str, Any]) -> None:
    _check_enum(buy_box.get("strategy"), VALID_STRATEGIES, "strategy")
    _check_enum(buy_box.get("property_type"), VALID_PROPERTY_TYPES, "property_type")
    _check_enum(buy_box.get("condition"), VALID_CONDITIONS, "condition")


def _validate_property_enums(prop: Mapping[str, Any]) -> None:
    # property_type and condition are NOT NULL on the properties table.
    _check_enum(prop.get("property_type"), VALID_PROPERTY_TYPES, "property_type")
    _check_enum(prop.get("condition"), VALID_CONDITIONS, "condition")


def _first_row(rows: Sequence[dict], context: str) -> dict:
    if not rows:
        raise DbError(f"{context}: insert returned no row")
    return rows[0]


# --------------------------------------------------------------------------- #
# Buy box fields persisted to the buy_boxes table.
# --------------------------------------------------------------------------- #

_BUY_BOX_FIELDS: tuple[str, ...] = (
    "markets",
    "strategy",
    "property_type",
    "price_min",
    "price_max",
    "arv_pct_max",
    "min_beds",
    "min_baths",
    "condition",
    "raw_text",
)

_PROPERTY_FIELDS: tuple[str, ...] = (
    "address",
    "city",
    "price",
    "arv",
    "beds",
    "baths",
    "sqft",
    "property_type",
    "condition",
)


def _project(source: Mapping[str, Any], fields: Iterable[str]) -> dict:
    """Return only the recognised ``fields`` present in ``source``."""
    return {f: source[f] for f in fields if f in source}


# --------------------------------------------------------------------------- #
# Insert / select helpers
# --------------------------------------------------------------------------- #


def insert_buyer_with_buy_box(
    *,
    name: str,
    buy_box: Mapping[str, Any],
    company: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    client: Any | None = None,
) -> dict:
    """Insert a Buyer and its one-to-one Buy_Box (Req 9.1, 9.2, 9.7).

    Returns ``{"buyer_id": <uuid>, "buyer": {...}, "buy_box": {...}}``.

    Enum values on the buy box are validated in-process first (Req 9.5). The
    buyer is inserted, then the buy box referencing it; the unique
    ``buyer_id`` constraint enforces the 1:1 association and a duplicate is
    surfaced as :class:`UniqueViolationError` (Req 9.7). If the buy_box insert
    fails the just-created buyer is rolled back (best-effort delete) so a
    rejected record leaves nothing persisted.
    """
    _validate_buy_box_enums(buy_box)

    conn = _resolve_client(client)

    buyer_payload: dict[str, Any] = {"name": name}
    if company is not None:
        buyer_payload["company"] = company
    if email is not None:
        buyer_payload["email"] = email
    if phone is not None:
        buyer_payload["phone"] = phone

    buyer_row = _first_row(
        _execute(conn.table(BUYERS_TABLE).insert(buyer_payload)),
        "insert buyer",
    )
    buyer_id = buyer_row["id"]

    buy_box_payload = _project(buy_box, _BUY_BOX_FIELDS)
    buy_box_payload["buyer_id"] = buyer_id

    try:
        buy_box_row = _first_row(
            _execute(conn.table(BUY_BOXES_TABLE).insert(buy_box_payload)),
            "insert buy_box",
        )
    except Exception:
        # Roll back the orphaned buyer so the rejected record is not persisted.
        _rollback_buyer(conn, buyer_id)
        raise

    return {"buyer_id": buyer_id, "buyer": buyer_row, "buy_box": buy_box_row}


def _rollback_buyer(conn: Any, buyer_id: Any) -> None:
    """Best-effort delete of a buyer whose buy_box insert failed."""
    try:
        _execute(conn.table(BUYERS_TABLE).delete().eq("id", buyer_id))
    except Exception:  # noqa: BLE001 - rollback is best-effort, never masks the cause
        pass


def list_buyers_with_buy_boxes(client: Any | None = None) -> list[dict]:
    """Return every Buyer with its embedded Buy_Box (Req 9.2; design GET /buyers).

    Each element is the buyer row plus a ``buy_box`` key holding the single
    associated buy box (or ``None`` if absent). Returns an empty list when no
    buyers are stored.
    """
    conn = _resolve_client(client)
    rows = _execute(
        conn.table(BUYERS_TABLE).select(f"*, {BUY_BOXES_TABLE}(*)")
    )

    buyers: list[dict] = []
    for row in rows:
        record = dict(row)
        embedded = record.pop(BUY_BOXES_TABLE, None)
        record["buy_box"] = _single_buy_box(embedded)
        buyers.append(record)
    return buyers


def get_buyer_with_buy_box(
    buyer_id: str, client: Any | None = None
) -> dict | None:
    """Return a single Buyer (with embedded Buy_Box) by id, or ``None``.

    Used by the message-draft route (Req 8.4 / 10.6) to distinguish an existing
    buyer from an unknown one *before* the drafter runs: a ``None`` result maps
    to HTTP 404 and the drafter is never invoked.

    The query filters server-side by ``id``; the returned rows are additionally
    matched in-process so the helper is correct even against a client that does
    not honour the filter. The embedded ``buy_boxes`` relation is normalised to
    a single ``buy_box`` entry (or ``None``) exactly as
    :func:`list_buyers_with_buy_boxes` does.
    """
    conn = _resolve_client(client)
    rows = _execute(
        conn.table(BUYERS_TABLE)
        .select(f"*, {BUY_BOXES_TABLE}(*)")
        .eq("id", buyer_id)
    )
    for row in rows:
        if str(row.get("id")) == str(buyer_id):
            record = dict(row)
            embedded = record.pop(BUY_BOXES_TABLE, None)
            record["buy_box"] = _single_buy_box(embedded)
            return record
    return None


def _single_buy_box(embedded: Any) -> dict | None:
    """Normalise PostgREST's embedded buy_box (list or object) to one row."""
    if embedded is None:
        return None
    if isinstance(embedded, list):
        return embedded[0] if embedded else None
    if isinstance(embedded, dict):
        return embedded
    return None


def insert_property(
    property: Mapping[str, Any], client: Any | None = None
) -> dict:
    """Insert a Property and return the stored row incl. generated ``id``.

    ``property_type`` and ``condition`` are validated in-process (Req 9.5).
    ``Deal_ARV_Pct`` is never written — the table has no such column (Req 9.6).
    """
    _validate_property_enums(property)

    conn = _resolve_client(client)
    payload = _project(property, _PROPERTY_FIELDS)
    return _first_row(
        _execute(conn.table(PROPERTIES_TABLE).insert(payload)),
        "insert property",
    )


def insert_match(
    *,
    property_id: str,
    buyer_id: str,
    score: int,
    reasons: Mapping[str, Any],
    client: Any | None = None,
) -> dict:
    """Insert a Match row and return it (Req 9.4, 9.8).

    A ``property_id`` or ``buyer_id`` that references no existing row is
    surfaced as :class:`ForeignKeyViolationError` with nothing persisted
    (Req 9.8).
    """
    conn = _resolve_client(client)
    payload = {
        "property_id": property_id,
        "buyer_id": buyer_id,
        "score": score,
        "reasons": dict(reasons),
    }
    return _first_row(
        _execute(conn.table(MATCHES_TABLE).insert(payload)),
        "insert match",
    )
