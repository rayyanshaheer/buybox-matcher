"""FastAPI application entry point and Match_Service orchestration.

This module owns FastAPI app construction, CORS middleware, the route handlers,
and (in later tasks) Match_Service orchestration (design: "API Layer").

The app is defined at module level so later tasks (5.4, 6.2, 8.1) can register
additional routes on the same ``app`` instance without restructuring. This task
(2.5) implements only app construction, ``GET /health`` (Req 10.7), and CORS
(Req 10.9, 10.10).
"""

from __future__ import annotations

from typing import Any, Mapping

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api import db
from api.config import load_settings
from api.extract import (
    EXTRACTION_TIMEOUT_SECONDS,
    ExtractionError,
    ProviderCallable,
    extract_buy_box,
)
from api.matching import order_and_limit
from api.messaging import draft_message
from api.models import (
    BuyBoxModel,
    ExtractRequest,
    ExtractResponse,
    ManualBuyerRequest,
    MatchItem,
    MatchReasons,
    MatchResponse,
    MessageDraft,
    PropertyInput,
    ScoringBuyBox,
    ScoringProperty,
)
from api.scoring import ScoringInputError, score

# --------------------------------------------------------------------------- #
# CORS configuration (design: "API Layer" / CORS; Req 10.9, 10.10)
# --------------------------------------------------------------------------- #

#: Development fallback used only when ``ALLOWED_ORIGIN`` is unset. The allowed
#: origin stays config-driven (Req 10.9, 10.10): in deployed environments
#: ``ALLOWED_ORIGIN`` is provided and this fallback is never used.
DEFAULT_ALLOWED_ORIGIN = "http://localhost:5173"


def _resolve_allowed_origin() -> str:
    """Resolve the single CORS-allowed origin from config (Req 10.9, 10.10).

    Reads ``ALLOWED_ORIGIN`` via :func:`api.config.load_settings`. When it is
    unset (e.g. local dev), falls back to :data:`DEFAULT_ALLOWED_ORIGIN` so the
    Vite dev server can talk to the API, while keeping the value config-driven.
    """
    settings = load_settings()
    return settings.allowed_origin or DEFAULT_ALLOWED_ORIGIN


# --------------------------------------------------------------------------- #
# Application construction
# --------------------------------------------------------------------------- #

app = FastAPI(title="BuyBox Matcher API")

# CORSMiddleware with a single configured origin. When an inbound request's
# Origin matches ALLOWED_ORIGIN, the response carries Access-Control-Allow-Origin
# (Req 10.9); otherwise the header is omitted (Req 10.10).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_resolve_allowed_origin()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe (Req 10.7): returns HTTP 200 ``{"status": "ok"}``."""
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# Match_Service orchestration (design: "Match_Service"; Req 7.1-7.7, 10.4)
#
# The route handler keeps query-param and body validation at the FastAPI edge
# (via Query constraints and the PropertyInput model) so invalid values yield a
# 422 *before* this orchestration runs — meaning nothing is persisted on a bad
# request (Req 7.8, 10.8). run_match() then performs the persistence + scoring
# pipeline described in the design's Match_Service steps.
# --------------------------------------------------------------------------- #


def _to_scoring_property(property_in: PropertyInput) -> ScoringProperty:
    """Adapt the validated API body to the pure engine's input dataclass.

    ``city`` and ``property_type`` are required (non-null) on ``PropertyInput``,
    so the engine's invalid-input contract (Req 2.10) is satisfied for the
    property side.
    """
    return ScoringProperty(
        city=property_in.city,
        property_type=property_in.property_type,
        condition=property_in.condition,
        price=property_in.price,
        arv=property_in.arv,
        beds=property_in.beds,
        baths=property_in.baths,
    )


def _to_scoring_buy_box(buy_box: Mapping[str, Any]) -> ScoringBuyBox:
    """Adapt a persisted buy_box row (dict) to the pure engine's input dataclass."""
    return ScoringBuyBox(
        markets=list(buy_box.get("markets") or []),
        strategy=buy_box.get("strategy"),
        property_type=buy_box.get("property_type"),
        price_min=buy_box.get("price_min"),
        price_max=buy_box.get("price_max"),
        arv_pct_max=buy_box.get("arv_pct_max"),
        min_beds=buy_box.get("min_beds"),
        min_baths=buy_box.get("min_baths"),
        condition=buy_box.get("condition"),
    )


def run_match(
    property_in: PropertyInput,
    min_score: int | None,
    limit: int | None,
) -> MatchResponse:
    """Persist a property, score it against every buyer, return ranked matches.

    Orchestration steps (design "Match_Service"; Req 7.1-7.7):

    1. (Query-param validation already happened at the route edge, before this
       call — see :func:`match`. Nothing is persisted on a bad request.)
    2. Persist the Property, obtaining ``property_id`` (Req 7.1).
    3. Load all buyers with their buy boxes.
    4. Score each buyer's buy box against the property via the pure engine.
    5. Persist each computed Match ``{property_id, buyer_id, score, reasons}``
       (Req 7.2).
    6. Sort by ``score`` desc, ``buyer_id`` asc, then apply ``min_score`` before
       ``limit`` (Req 7.3, 7.6, 7.7).
    7. Return ``{property_id, matches}``; an empty buyer set yields an empty
       ``matches`` array, still 200 (Req 7.5).

    Persistence flows through the :mod:`api.db` module-level helpers, which read
    the shared (injectable) client; tests inject a fake via ``db.set_client``.
    """
    # 2. Persist the property (Req 7.1). Deal_ARV_Pct is never stored (Req 9.6);
    # db.insert_property projects only the known property columns.
    property_row = db.insert_property(property_in.model_dump())
    property_id = property_row["id"]

    # 3. Load every saved buyer with its embedded buy box.
    buyers = db.list_buyers_with_buy_boxes()

    scoring_property = _to_scoring_property(property_in)

    # 4 + 5. Score each buyer and persist the resulting Match.
    matches: list[MatchItem] = []
    for buyer in buyers:
        buy_box = buyer.get("buy_box")
        if not buy_box:
            # A buyer without a buy box cannot be scored; skip it (the 1:1
            # association normally guarantees one exists).
            continue

        try:
            result = score(scoring_property, _to_scoring_buy_box(buy_box))
        except ScoringInputError:
            # Defensive: a buy box missing required scoring fields is skipped
            # rather than failing the whole request.
            continue

        reasons = {"fit": result.reasons.fit, "risk": result.reasons.risk}
        db.insert_match(
            property_id=property_id,
            buyer_id=buyer["id"],
            score=result.score,
            reasons=reasons,
        )

        matches.append(
            MatchItem(
                buyer_id=buyer["id"],
                name=buyer.get("name") or "",
                score=result.score,
                reasons=MatchReasons(fit=result.reasons.fit, risk=result.reasons.risk),
            )
        )

    # 6. Sort (score desc, buyer_id asc), filter by min_score, then limit.
    ranked = order_and_limit(matches, min_score=min_score, limit=limit)

    # 7. Return 200 payload (empty matches array when no buyers / no matches).
    return MatchResponse(property_id=property_id, matches=ranked)


@app.post("/match", response_model=MatchResponse)
def match(
    property_in: PropertyInput,
    min_score: int | None = Query(default=None, ge=0, le=100),
    limit: int | None = Query(default=None, ge=1),
) -> MatchResponse:
    """Score a property against all buyers and return a ranked list (Req 10.4).

    Query params are constrained at the edge so invalid values are rejected with
    HTTP 422 *before* the handler body runs — nothing is persisted (Req 7.8):

    * ``min_score`` must be an integer in ``[0, 100]`` (``ge=0, le=100``).
    * ``limit`` must be an integer ``>= 1`` (``ge=1``).

    A malformed JSON body is likewise rejected with 422 by the ``PropertyInput``
    model before any persistence (Req 10.8). On success returns HTTP 200 with
    ``{property_id, matches}`` sorted by ``score`` descending (Req 7.4).
    """
    return run_match(property_in, min_score, limit)


# --------------------------------------------------------------------------- #
# Extraction + buyer listing (design: "API Layer"; Req 1.1, 1.7, 1.9, 1.11,
# 10.1, 10.2, 10.3)
#
# The AI provider call is isolated behind two dependency seams so the whole
# extraction pipeline can be integration-tested with a mocked provider and no
# live API calls (task 6.5). In production both seams resolve to their defaults:
# `get_extraction_provider` returns None (extract_buy_box builds the configured
# provider) and `get_extraction_timeout` returns the 30s ceiling (Req 1.9).
# Tests override them via `app.dependency_overrides`.
# --------------------------------------------------------------------------- #

#: Fallback Buyer name when the extract request omits one. The buyers table
#: requires a non-null name; extraction does not always carry one.
DEFAULT_BUYER_NAME = "Unknown Buyer"


def get_extraction_provider() -> ProviderCallable | None:
    """Provider seam for extraction (design "Testability seam").

    Returns ``None`` so :func:`api.extract.extract_buy_box` falls back to the
    configured module-level provider. Tests override this dependency to inject
    a mock ``(system, user) -> str`` callable, exercising the full pipeline with
    no live provider call.
    """
    return None


def get_extraction_timeout() -> float:
    """Timeout seam for extraction (Req 1.9).

    Defaults to the 30-second ceiling. Tests override this to a tiny value to
    exercise the timeout path quickly.
    """
    return EXTRACTION_TIMEOUT_SECONDS


#: Maps an :class:`ExtractionError` ``kind`` to the HTTP status the route
#: returns. Parse/validation failures are client-correctable input problems
#: (422, Req 1.7, 1.10, 10.2); a provider error or timeout is an upstream
#: failure surfaced as an error status with nothing persisted (Req 1.9).
_EXTRACTION_ERROR_STATUS: dict[str, int] = {
    "parse": 422,
    "validation": 422,
    "timeout": 504,
    "provider": 502,
}


@app.post("/buy-boxes/extract", response_model=ExtractResponse, status_code=201)
def extract(
    body: ExtractRequest,
    provider: ProviderCallable | None = Depends(get_extraction_provider),
    timeout: float = Depends(get_extraction_timeout),
    x_openai_key: str | None = Header(default=None),
) -> ExtractResponse:
    """Extract a Buy_Box from free text and persist the buyer (Req 1.1-1.11, 10.1).

    Body validation happens at the FastAPI edge: a missing/whitespace-only
    ``raw_text`` is rejected with 422 by the :class:`ExtractRequest` validator
    *before* this handler runs, so the AI provider is never invoked and nothing
    is persisted (Req 1.8).

    Supports BYOK (Bring Your Own Key): if the ``X-OpenAI-Key`` header is
    present, it overrides the server-side AI key for this request only.

    On a valid body the extraction pipeline runs; any failure raises
    :class:`ExtractionError`, which maps to 422 (unparseable / validation) or an
    upstream error status (provider / timeout) with nothing persisted
    (Req 1.7, 1.9, 1.10, 10.2). On success the buyer + buy_box are persisted 1:1
    and the route returns 201 ``{buyer_id, buy_box}`` (Req 1.11).
    """
    # Build a provider using the user-supplied key if present.
    effective_provider = provider
    if effective_provider is None and x_openai_key:
        from api.extract import build_provider as _build_provider

        try:
            built = _build_provider(user_api_key=x_openai_key)
            effective_provider = built.complete_json
        except ExtractionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    try:
        buy_box = extract_buy_box(
            body.raw_text, provider=effective_provider, timeout=timeout
        )
    except ExtractionError as exc:
        status_code = _EXTRACTION_ERROR_STATUS.get(exc.kind, 502)
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    # Persist buyer + buy_box (1:1). raw_text is a required buy_box column and is
    # not part of the extracted schema, so it is attached here.
    result = db.insert_buyer_with_buy_box(
        name=body.name or DEFAULT_BUYER_NAME,
        company=body.company,
        buy_box={**buy_box.model_dump(), "raw_text": body.raw_text},
    )
    return ExtractResponse(buyer_id=result["buyer_id"], buy_box=buy_box)


@app.get("/buyers")
def list_buyers() -> list[dict]:
    """List every buyer with its buy_box (Req 10.3).

    Returns HTTP 200 with an array of ``{buyer_id, name, company, buy_box}``;
    the array is empty when no buyers are saved.
    """
    buyers = db.list_buyers_with_buy_boxes()
    return [
        {
            "buyer_id": buyer["id"],
            "name": buyer.get("name"),
            "company": buyer.get("company"),
            "buy_box": buyer.get("buy_box"),
        }
        for buyer in buyers
    ]


@app.post("/buyers/manual", status_code=201)
def create_buyer_manual(body: ManualBuyerRequest) -> dict:
    """Create a buyer with manually-entered buy box criteria (no AI).

    Accepts structured buy box fields directly, persists the buyer + buy_box,
    and returns ``{buyer_id, buy_box}``. No API key needed.
    """
    buy_box_data = {
        "markets": body.markets,
        "strategy": body.strategy,
        "property_type": body.property_type,
        "price_min": body.price_min,
        "price_max": body.price_max,
        "arv_pct_max": body.arv_pct_max,
        "min_beds": body.min_beds,
        "min_baths": body.min_baths,
        "condition": body.condition,
        "raw_text": "(manual entry)",
    }
    result = db.insert_buyer_with_buy_box(
        name=body.name,
        company=body.company,
        buy_box=buy_box_data,
    )
    return {"buyer_id": result["buyer_id"], "buy_box": buy_box_data}


# --------------------------------------------------------------------------- #
# Message_Drafter route (design: "API Layer"; Req 8.1-8.4, 10.5, 10.6, 15.1)
#
# The buyer is looked up *before* the drafter runs so an unknown buyer maps to
# HTTP 404 with the drafter never invoked (Req 8.4, 10.6). The drafter composes
# text only and performs zero outbound delivery (Req 8.3, 15.1).
#
# An optional PropertyInput body lets a caller supply the deal being pitched so
# the draft can reference its address/city (Req 8.1). The frontend draft control
# sends no body, in which case the property reference is omitted and the draft
# references the buyer's market only.
# --------------------------------------------------------------------------- #


@app.post("/match/{buyer_id}/message", response_model=MessageDraft)
def draft_buyer_message(
    buyer_id: str,
    property_in: PropertyInput | None = Body(default=None),
) -> MessageDraft:
    """Draft a first-touch SMS for an existing buyer (Req 8.1, 8.2, 10.5).

    Looks up the buyer (with its buy_box) first: an unknown ``buyer_id`` returns
    HTTP 404 and the :func:`~api.messaging.draft_message` drafter is never
    invoked (Req 8.4, 10.6). For an existing buyer the drafter builds a
    deterministic SMS draft referencing a buyer market (and the property's
    address/city when a body is supplied) and the route returns HTTP 200
    ``{channel: "sms", text}`` (Req 8.2, 10.5). Nothing is ever transmitted
    (Req 8.3, 15.1).
    """
    buyer = db.get_buyer_with_buy_box(buyer_id)
    if buyer is None:
        raise HTTPException(status_code=404, detail="buyer not found")

    buy_box = buyer.get("buy_box") or {}
    return draft_message(buyer, buy_box, property_in)
