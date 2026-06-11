"""Synthetic seed data generator (design: ``api/scripts/seed.py``, Req 11).

This script populates the database with synthetic-only Buyers and Buy_Boxes so
the Match flow works on first clone without any manual data entry. It has two
clearly separated halves so the generation logic is unit-testable without a
live database (Task 7.2 verifies it):

1. :func:`generate_seed_buyers` — a **pure** function. Given a ``count`` and an
   optional ``seed`` it returns a deterministic list of buyer dicts (each with
   an embedded ``buy_box``). It performs no I/O. Every value it produces obeys
   the Req 11.4/11.5 constraints (allowed markets, price/ARV%/beds/baths
   ranges, valid enums, non-empty synthetic ``raw_text``) and the dataset is
   guaranteed to cover all four Strategy values and all four Property_Type
   values via eight explicit coverage fixtures (Req 11.4).

2. :func:`run_seed` — the **persistence** half. It detects any previously
   seeded synthetic dataset, clears it, then inserts a freshly generated set
   so reruns never duplicate rows and never push the synthetic Buyer count
   outside the 140-160 range (Req 11.1, 11.2). Detection + clear + reinsert is
   treated as a single logical unit.

**Idempotency marker (Req 11.2, 11.3).** Every seeded Buyer is tagged as
synthetic in two redundant ways: its ``email`` uses the reserved
``@seed.example`` domain and its ``company`` carries a ``[seed]`` suffix.
Detection keys on the email domain, which a real buyer would never use, so the
synthetic set is unambiguously identifiable on rerun.
"""

from __future__ import annotations

import random
from typing import Any, Mapping, Sequence

from api import db

# --------------------------------------------------------------------------- #
# Synthetic markers, vocabularies and value ranges (Req 11.3, 11.4, 11.5)
# --------------------------------------------------------------------------- #

#: Reserved email domain that flags a Buyer as part of the synthetic seed set.
#: A real investor record would never use this domain, so it is a safe sentinel
#: for idempotent detection (Req 11.2, 11.3).
SEED_EMAIL_DOMAIN = "seed.example"

#: Redundant human-visible synthetic marker appended to every seeded company.
SEED_COMPANY_SUFFIX = "[seed]"

#: Default number of buyers to seed; well within the required 140-160 band.
DEFAULT_SEED_COUNT = 150

#: Inclusive bounds on the size of the synthetic dataset (Req 11.1, 11.2).
MIN_SEED_COUNT = 140
MAX_SEED_COUNT = 160

#: The only cities/metros a seeded Buy_Box may target (Req 11.4).
ALLOWED_MARKETS: tuple[str, ...] = (
    "Tampa",
    "Lakeland",
    "Orlando",
    "Dallas",
    "Houston",
    "Cleveland",
    "Nashville",
    "Jacksonville",
)

STRATEGIES: tuple[str, ...] = ("fix_and_flip", "buy_and_hold", "brrrr", "wholesale")
PROPERTY_TYPES: tuple[str, ...] = ("single_family", "multi_family", "condo", "land")
CONDITIONS: tuple[str, ...] = ("distressed", "light_rehab", "turnkey", "any")

# Numeric value ranges (Req 11.5).
PRICE_FLOOR = 50_000
PRICE_CEILING = 600_000
ARV_PCT_MIN = 65
ARV_PCT_MAX = 80
MIN_BEDS_FLOOR = 0
MIN_BEDS_CEILING = 6
MIN_BATHS_FLOOR = 0.0
MIN_BATHS_CEILING = 5.0
#: Half-step bath minimums kept within [0, 5] (numeric column, Req 9.2/11.5).
MIN_BATHS_CHOICES: tuple[float, ...] = (
    0.0, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0,
)

# --------------------------------------------------------------------------- #
# Synthetic name / company pools (Req 11.3 — no real investor data).
# --------------------------------------------------------------------------- #

_FIRST_NAMES: tuple[str, ...] = (
    "Avery", "Blake", "Casey", "Dakota", "Emerson", "Finley", "Gray", "Harlow",
    "Indigo", "Jordan", "Kai", "Logan", "Marlowe", "Noor", "Oakley", "Parker",
    "Quinn", "Reese", "Sawyer", "Tatum", "Ursa", "Vesper", "Wren", "Yael",
)

_LAST_NAMES: tuple[str, ...] = (
    "Ashford", "Brookman", "Calloway", "Denton", "Eastwood", "Fairbanks",
    "Greenwood", "Holloway", "Ironwood", "Jessup", "Kingsley", "Larkspur",
    "Maddox", "Northcott", "Ormsby", "Pinewood", "Quill", "Rivendell",
    "Stonebridge", "Thornbury", "Underhill", "Vanmeter", "Westlake", "York",
)

_COMPANY_PREFIXES: tuple[str, ...] = (
    "Blue Harbor", "Cedar Peak", "Granite", "Lighthouse", "Maple Court",
    "Northstar", "Oak & Iron", "Pioneer", "Redwood", "Silverline",
    "Summit Ridge", "Tidewater", "Vantage", "Willow Creek",
)

_COMPANY_SUFFIXES: tuple[str, ...] = (
    "Capital", "Holdings", "Investments", "Partners", "Properties",
    "Realty Group", "Ventures",
)


# --------------------------------------------------------------------------- #
# Eight explicit coverage fixtures (Req 11.4).
#
# Each entry pins a (strategy, property_type) pair. Collectively they cover all
# four strategies AND all four property types (each appears at least once), so
# the dataset satisfies Req 11.4 regardless of how the randomized remainder
# turns out. The remaining fields are still randomized per fixture for variety.
# --------------------------------------------------------------------------- #

_COVERAGE_FIXTURES: tuple[tuple[str, str], ...] = (
    ("fix_and_flip", "single_family"),
    ("buy_and_hold", "multi_family"),
    ("brrrr", "condo"),
    ("wholesale", "land"),
    ("fix_and_flip", "condo"),
    ("buy_and_hold", "single_family"),
    ("brrrr", "land"),
    ("wholesale", "multi_family"),
)


# --------------------------------------------------------------------------- #
# Pure generation (no I/O) — Req 11.1, 11.3, 11.4, 11.5
# --------------------------------------------------------------------------- #


def _slugify(text: str) -> str:
    """Lowercase ``text`` into an email-local-part-safe slug."""
    out = []
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in {" ", "-", "&", "."}:
            out.append(".")
    slug = "".join(out).strip(".")
    while ".." in slug:
        slug = slug.replace("..", ".")
    return slug or "buyer"


def _pick_markets(rng: random.Random) -> list[str]:
    """Pick 1-3 distinct allowed markets (Req 11.4)."""
    n = rng.randint(1, 3)
    return rng.sample(ALLOWED_MARKETS, n)


def _pick_price_range(rng: random.Random) -> tuple[int, int]:
    """Pick ``(price_min, price_max)`` in [50k, 600k] with min <= max (Req 11.5)."""
    a = rng.randrange(PRICE_FLOOR, PRICE_CEILING + 1, 5_000)
    b = rng.randrange(PRICE_FLOOR, PRICE_CEILING + 1, 5_000)
    lo, hi = (a, b) if a <= b else (b, a)
    return lo, hi


def _build_raw_text(
    rng: random.Random,
    *,
    markets: Sequence[str],
    strategy: str,
    property_type: str,
    condition: str,
    price_min: int,
    price_max: int,
    arv_pct_max: int,
    min_beds: int,
    min_baths: float,
) -> str:
    """Compose a non-empty, synthetic investor-style note (Req 11.5).

    The text references the buy box's own values so it reads like a real
    free-text message while remaining entirely synthetic.
    """
    market_phrase = " / ".join(markets)
    type_phrase = property_type.replace("_", " ")
    strat_phrase = strategy.replace("_", " ")
    cond_phrase = condition.replace("_", " ")
    templates = (
        (
            f"Looking for {cond_phrase} {type_phrase} deals in {market_phrase}. "
            f"Running a {strat_phrase} strategy, budget ${price_min:,}-${price_max:,}, "
            f"need ARV under {arv_pct_max}% and at least {min_beds}bd/{min_baths}ba."
        ),
        (
            f"Active {strat_phrase} buyer in {market_phrase}. Send {type_phrase} "
            f"in {cond_phrase} condition, ${price_min:,} to ${price_max:,}, "
            f"max {arv_pct_max}% ARV, minimum {min_beds} beds and {min_baths} baths."
        ),
        (
            f"Cash buyer here - {market_phrase} only. I do {strat_phrase} on "
            f"{type_phrase}. {cond_phrase.capitalize()} is fine. Price band "
            f"${price_min:,}-${price_max:,}, ARV ceiling {arv_pct_max}%, "
            f"{min_beds}+ beds / {min_baths}+ baths."
        ),
    )
    return rng.choice(templates)


def _make_buyer(
    rng: random.Random,
    *,
    index: int,
    strategy: str,
    property_type: str,
) -> dict[str, Any]:
    """Build one synthetic buyer dict (with embedded buy_box) for ``index``.

    ``strategy`` and ``property_type`` are supplied by the caller (fixed for
    coverage fixtures, randomized for the remainder); all other fields are
    drawn here within the Req 11.5 ranges.
    """
    first = rng.choice(_FIRST_NAMES)
    last = rng.choice(_LAST_NAMES)
    name = f"{first} {last}"
    company = f"{rng.choice(_COMPANY_PREFIXES)} {rng.choice(_COMPANY_SUFFIXES)} {SEED_COMPANY_SUFFIX}"
    # Index keeps the email unique even when names collide.
    email = f"{_slugify(name)}.{index}@{SEED_EMAIL_DOMAIN}"
    phone = f"+1555{rng.randint(0, 9_999_999):07d}"

    markets = _pick_markets(rng)
    price_min, price_max = _pick_price_range(rng)
    arv_pct_max = rng.randint(ARV_PCT_MIN, ARV_PCT_MAX)
    condition = rng.choice(CONDITIONS)
    min_beds = rng.randint(MIN_BEDS_FLOOR, MIN_BEDS_CEILING)
    min_baths = rng.choice(MIN_BATHS_CHOICES)

    raw_text = _build_raw_text(
        rng,
        markets=markets,
        strategy=strategy,
        property_type=property_type,
        condition=condition,
        price_min=price_min,
        price_max=price_max,
        arv_pct_max=arv_pct_max,
        min_beds=min_beds,
        min_baths=min_baths,
    )

    buy_box = {
        "markets": markets,
        "strategy": strategy,
        "property_type": property_type,
        "price_min": price_min,
        "price_max": price_max,
        "arv_pct_max": arv_pct_max,
        "min_beds": min_beds,
        "min_baths": min_baths,
        "condition": condition,
        "raw_text": raw_text,
    }

    return {
        "name": name,
        "company": company,
        "email": email,
        "phone": phone,
        "buy_box": buy_box,
    }


def generate_seed_buyers(
    count: int = DEFAULT_SEED_COUNT, *, seed: int | None = 1337
) -> list[dict[str, Any]]:
    """Return ``count`` synthetic buyer dicts (each with an embedded buy_box).

    Pure and deterministic: identical ``count`` + ``seed`` always produce an
    identical list, and the function performs no I/O. The first eight buyers
    are the explicit coverage fixtures guaranteeing every Strategy and every
    Property_Type is represented (Req 11.4); the remainder randomize their
    strategy/property_type along with all other fields. All values obey the
    Req 11.5 ranges and use only allowed markets (Req 11.4).

    ``count`` must be within the required 140-160 dataset band (Req 11.1).
    """
    if not (MIN_SEED_COUNT <= count <= MAX_SEED_COUNT):
        raise ValueError(
            f"seed count must be between {MIN_SEED_COUNT} and {MAX_SEED_COUNT} "
            f"inclusive (Req 11.1), got {count}"
        )

    rng = random.Random(seed)
    buyers: list[dict[str, Any]] = []

    # 1) Eight explicit coverage fixtures first (Req 11.4).
    for i, (strategy, property_type) in enumerate(_COVERAGE_FIXTURES):
        buyers.append(
            _make_buyer(rng, index=i, strategy=strategy, property_type=property_type)
        )

    # 2) Randomized remainder.
    for i in range(len(_COVERAGE_FIXTURES), count):
        buyers.append(
            _make_buyer(
                rng,
                index=i,
                strategy=rng.choice(STRATEGIES),
                property_type=rng.choice(PROPERTY_TYPES),
            )
        )

    return buyers


# --------------------------------------------------------------------------- #
# Persistence (idempotent) — Req 11.1, 11.2
# --------------------------------------------------------------------------- #


def _is_synthetic(buyer: Mapping[str, Any]) -> bool:
    """True when a buyer row carries the synthetic seed email marker."""
    email = buyer.get("email") or ""
    return email.endswith(f"@{SEED_EMAIL_DOMAIN}")


def find_synthetic_buyers(client: Any | None = None) -> list[dict]:
    """Return every previously seeded synthetic Buyer currently stored.

    Uses :func:`api.db.list_buyers_with_buy_boxes` and filters on the reserved
    email domain so only synthetic rows are returned (Req 11.2).
    """
    return [
        buyer
        for buyer in db.list_buyers_with_buy_boxes(client=client)
        if _is_synthetic(buyer)
    ]


def _clear_synthetic_buyers(conn: Any, synthetic: Sequence[Mapping[str, Any]]) -> int:
    """Delete the given synthetic buyers; cascades remove their buy_boxes.

    Returns the number of buyers deleted. ``buy_boxes`` rows are removed
    automatically by the ``on delete cascade`` foreign key (see the migration),
    so clearing the buyer is sufficient to leave nothing behind.
    """
    deleted = 0
    for buyer in synthetic:
        buyer_id = buyer.get("id")
        if buyer_id is None:
            continue
        conn.table(db.BUYERS_TABLE).delete().eq("id", buyer_id).execute()
        deleted += 1
    return deleted


def run_seed(
    count: int = DEFAULT_SEED_COUNT,
    *,
    seed: int | None = 1337,
    client: Any | None = None,
) -> dict[str, Any]:
    """Idempotently seed the database with the synthetic dataset (Req 11.1, 11.2).

    Behavior:

    1. Detect any existing synthetic Buyers (via the reserved email domain).
    2. Clear them (cascade also removes their buy_boxes) so a rerun never
       duplicates rows and never pushes the synthetic count outside 140-160.
    3. Insert a freshly generated set of ``count`` buyers, each with exactly one
       buy_box, using :func:`api.db.insert_buyer_with_buy_box`.

    Detection + clear + reinsert form one logical unit so the synthetic set is
    replaced atomically from the caller's perspective. Returns a summary dict
    ``{"generated", "deleted", "inserted", "total_synthetic", "mode"}``.

    Passing ``client`` injects a Supabase-compatible client (used in tests);
    otherwise the shared lazy client from :func:`api.db.get_client` is used.
    """
    conn = client if client is not None else db.get_client()

    # 1) Detect and 2) clear any prior synthetic dataset.
    existing = find_synthetic_buyers(client=conn)
    deleted = _clear_synthetic_buyers(conn, existing)

    # 3) Generate and insert the fresh dataset.
    buyers = generate_seed_buyers(count, seed=seed)
    inserted = 0
    for buyer in buyers:
        db.insert_buyer_with_buy_box(
            name=buyer["name"],
            company=buyer["company"],
            email=buyer["email"],
            phone=buyer.get("phone"),
            buy_box=buyer["buy_box"],
            client=conn,
        )
        inserted += 1

    return {
        "generated": len(buyers),
        "deleted": deleted,
        "inserted": inserted,
        "total_synthetic": inserted,
        "mode": "cleared_and_reinserted" if deleted else "inserted_fresh",
    }


def main() -> None:
    """CLI entry point: seed the database using the shared Supabase client."""
    summary = run_seed()
    print(
        "Seed complete: "
        f"generated={summary['generated']} "
        f"deleted={summary['deleted']} "
        f"inserted={summary['inserted']} "
        f"mode={summary['mode']}"
    )


if __name__ == "__main__":  # pragma: no cover - manual invocation path
    main()
