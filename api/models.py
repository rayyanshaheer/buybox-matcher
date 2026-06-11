"""Pydantic request/response models and internal scoring dataclasses.

This module holds two distinct families of types:

1. **Pydantic models** that define the API request/response boundary. These
   coerce and validate inbound JSON, rejecting out-of-vocabulary enum values,
   whitespace-only ``raw_text``, and invalid price ranges at the edge
   (Requirements 1.2, 1.8, 1.10, 9.5).

2. **Internal frozen dataclasses** consumed by the pure Scoring_Engine
   (``api/scoring.py``). The design's scoring signature refers to
   ``PropertyInput``/``BuyBoxInput``; because ``PropertyInput`` is already a
   Pydantic API model here, the scoring inputs are named ``ScoringProperty``
   and ``ScoringBuyBox`` to avoid a name collision. ``ScoreResult`` and
   ``Reasons`` carry the engine's output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enum literals (Req 9.5) — unknown values are rejected at the boundary.
# ---------------------------------------------------------------------------

Strategy = Literal["fix_and_flip", "buy_and_hold", "brrrr", "wholesale"]
PropertyType = Literal["single_family", "multi_family", "condo", "land"]
Condition = Literal["distressed", "light_rehab", "turnkey", "any"]


# ---------------------------------------------------------------------------
# API request/response models (Pydantic)
# ---------------------------------------------------------------------------


class ExtractRequest(BaseModel):
    """Body for ``POST /buy-boxes/extract`` (Req 1.8, 10.1)."""

    raw_text: str = Field(min_length=1, max_length=10_000)
    name: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=200)

    @field_validator("raw_text")
    @classmethod
    def not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("raw_text is required")  # -> 422 (1.8, 8)
        return v


class BuyBoxModel(BaseModel):
    """Structured buy box returned by extraction / persisted for a buyer."""

    markets: list[str]
    strategy: Strategy | None
    property_type: PropertyType | None
    price_min: int | None
    price_max: int | None
    arv_pct_max: int | None = Field(default=None, ge=0, le=100)
    min_beds: int | None
    min_baths: float | None
    condition: Condition | None

    @model_validator(mode="after")
    def price_range_valid(self) -> "BuyBoxModel":
        if (
            self.price_min is not None
            and self.price_max is not None
            and self.price_min > self.price_max
        ):
            raise ValueError("price_min must be <= price_max")  # -> 422 (1.10)
        return self


class ExtractResponse(BaseModel):
    """Response for a successful extraction + save (Req 1.11, 10.1)."""

    buyer_id: str
    buy_box: BuyBoxModel


class PropertyInput(BaseModel):
    """Body for ``POST /match`` describing a property deal (Req 10.4)."""

    address: str
    city: str
    price: int
    arv: int
    beds: int | None
    baths: float | None
    sqft: int | None = None
    property_type: PropertyType
    condition: Condition


class MatchReasons(BaseModel):
    """Plain-English fit/risk explanations attached to a match (Req 2.4)."""

    fit: list[str]
    risk: list[str]


class MatchItem(BaseModel):
    """One ranked buyer match (Req 7.3, 10.4)."""

    buyer_id: str
    name: str
    score: int = Field(ge=0, le=100)
    reasons: MatchReasons


class MatchResponse(BaseModel):
    """Response for ``POST /match`` (Req 7.4, 10.4)."""

    property_id: str
    matches: list[MatchItem]


class MessageDraft(BaseModel):
    """Response for ``POST /match/{buyer_id}/message`` (Req 8.2, 10.5)."""

    channel: Literal["sms"]
    text: str = Field(min_length=1, max_length=480)


# ---------------------------------------------------------------------------
# Internal frozen dataclasses for the pure Scoring_Engine (api/scoring.py).
#
# These are deliberately decoupled from the Pydantic API models so the engine
# stays a pure, I/O-free function over plain values. They are frozen so the
# engine cannot mutate its inputs (Req 2.1, 2.10).
#
# NOTE for downstream tasks (e.g. 3.1): import these as
#   from api.models import ScoringProperty, ScoringBuyBox, ScoreResult, Reasons
# ``BuyBoxInput`` / ``PropertyInputScoring`` aliases are provided for
# convenience to match the design's signature naming.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScoringProperty:
    """Property values the Scoring_Engine reads.

    ``city`` and ``property_type`` are required for scoring; absence is
    handled by the engine's invalid-input contract (Req 2.10).
    """

    city: str
    property_type: str
    condition: str | None = None
    price: int | None = None
    arv: int | None = None
    beds: int | None = None
    baths: float | None = None


@dataclass(frozen=True)
class ScoringBuyBox:
    """Buy box values the Scoring_Engine reads.

    ``markets`` is required for scoring; absence is handled by the engine's
    invalid-input contract (Req 2.10).
    """

    markets: list[str] = field(default_factory=list)
    strategy: str | None = None
    property_type: str | None = None
    price_min: int | None = None
    price_max: int | None = None
    arv_pct_max: int | None = None
    min_beds: int | None = None
    min_baths: float | None = None
    condition: str | None = None


@dataclass(frozen=True)
class Reasons:
    """Fit/risk reason lists produced by the engine (Req 2.4)."""

    fit: list[str]
    risk: list[str]


@dataclass(frozen=True)
class ScoreResult:
    """Output of ``score(property, buy_box)`` (Req 2.3, 2.4)."""

    score: int  # 0..100 inclusive
    reasons: Reasons


# Aliases matching the design's scoring signature names. Downstream code may
# import either the descriptive names above or these design-aligned aliases.
BuyBoxInput = ScoringBuyBox
PropertyInputScoring = ScoringProperty
