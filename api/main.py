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

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from api import db
from api.config import load_settings
from api.matching import order_and_limit
from api.models import (
    MatchItem,
    MatchReasons,
    MatchResponse,
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
