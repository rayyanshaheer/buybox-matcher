"""Environment loading, startup credential validation, and Scoring_Config.

This module owns three responsibilities (design: "Secret Handling",
"Provider Selection", and the Scoring_Engine weights/thresholds):

1. Read the backend environment configuration (``AI_PROVIDER``, the selected
   provider API key, ``SUPABASE_URL``, ``SUPABASE_KEY``, ``ALLOWED_ORIGIN``).
2. Provide :func:`validate_config`, a callable that verifies every required
   credential is present and non-empty. On failure it raises
   :class:`ConfigError` naming the offending variable(s) **without ever
   exposing the credential value** (Req 14.3, 14.4). It is a function, not
   import-time logic, so importing this module never crashes (e.g. in tests).
3. Define :class:`ScoringConfig` and the :data:`SCORING_CONFIG` constant that
   hold every weight and threshold the Scoring_Engine consumes (Req 2.2).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

# --------------------------------------------------------------------------- #
# Provider selection (design: "Provider Selection")
# --------------------------------------------------------------------------- #

#: The AI providers the backend knows how to talk to.
VALID_AI_PROVIDERS: tuple[str, ...] = ("openai", "anthropic")

#: Maps a selected provider to the environment variable holding its API key.
PROVIDER_KEY_VAR: Mapping[str, str] = MappingProxyType(
    {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }
)


class ConfigError(RuntimeError):
    """Raised when required backend configuration is missing or invalid.

    The message names the offending environment variable(s) but never the
    value, so secrets are not leaked into logs (Req 14.4).
    """


# --------------------------------------------------------------------------- #
# Environment settings
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Settings:
    """Snapshot of the backend environment configuration.

    All fields are optional at read time; presence is enforced separately by
    :func:`validate_config` so that merely importing or constructing settings
    never raises.
    """

    ai_provider: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    supabase_url: str | None = None
    supabase_key: str | None = None
    allowed_origin: str | None = None

    @property
    def provider_api_key(self) -> str | None:
        """The API key for the currently selected provider, if determinable."""
        provider = (self.ai_provider or "").strip().lower()
        if provider == "openai":
            return self.openai_api_key
        if provider == "anthropic":
            return self.anthropic_api_key
        return None


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read the backend configuration from the environment (Req 14.3).

    Reading never fails: missing variables become ``None``. Pass ``env`` to
    read from an explicit mapping (useful in tests); defaults to ``os.environ``.
    """
    source: Mapping[str, str] = os.environ if env is None else env

    def get(key: str) -> str | None:
        value = source.get(key)
        return value if value else None

    return Settings(
        ai_provider=get("AI_PROVIDER"),
        openai_api_key=get("OPENAI_API_KEY"),
        anthropic_api_key=get("ANTHROPIC_API_KEY"),
        supabase_url=get("SUPABASE_URL"),
        supabase_key=get("SUPABASE_KEY"),
        allowed_origin=get("ALLOWED_ORIGIN"),
    )


def validate_config(settings: Settings | None = None) -> Settings:
    """Validate required backend credentials, halting AI-dependent startup.

    Required credentials (Req 14.4): ``SUPABASE_URL`` and ``SUPABASE_KEY``.
    ``AI_PROVIDER`` and the selected provider's API key are optional when
    operating in BYOK mode (users supply their own key per request).
    ``ALLOWED_ORIGIN`` is read but not required for startup.

    Returns the validated :class:`Settings` on success. Raises
    :class:`ConfigError` naming the missing/invalid variable(s) — never their
    values — on failure.
    """
    settings = settings if settings is not None else load_settings()

    def is_blank(value: str | None) -> bool:
        return not (value or "").strip()

    missing: list[str] = []

    provider = (settings.ai_provider or "").strip().lower()
    if not is_blank(settings.ai_provider) and provider not in VALID_AI_PROVIDERS:
        # Note: deliberately does not echo the offending value (Req 14.4).
        raise ConfigError(
            "AI_PROVIDER is set to an unsupported value; expected one of: "
            + ", ".join(VALID_AI_PROVIDERS)
        )

    if is_blank(settings.supabase_url):
        missing.append("SUPABASE_URL")
    if is_blank(settings.supabase_key):
        missing.append("SUPABASE_KEY")

    if missing:
        raise ConfigError(
            "Missing or empty required environment variable(s): "
            + ", ".join(missing)
        )

    return settings


# --------------------------------------------------------------------------- #
# Scoring_Config (Req 2.2; design: Scoring_Engine weights/thresholds)
# --------------------------------------------------------------------------- #

# Strategy mapping (design "Component: Strategy"): a property condition maps to
# the set of buyer strategies it suits. `wholesale` suits any condition and is
# handled separately (see `wholesale_fits_any`).
_STRATEGY_BY_CONDITION: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "distressed": ("fix_and_flip", "brrrr"),
        "light_rehab": ("fix_and_flip", "brrrr"),
        "turnkey": ("buy_and_hold",),
    }
)


@dataclass(frozen=True)
class ScoringConfig:
    """All weights and thresholds consumed by the Scoring_Engine (Req 2.2).

    The six component weights MUST sum to exactly 100
    (Market 30, Strategy 20, Price 20, ARV% 15, Property_Type 10, Beds/Baths 5).
    """

    # Component weights — must sum to 100 (Req 2.2).
    weight_market: int = 30
    weight_strategy: int = 20
    weight_price: int = 20
    weight_arv: int = 15
    weight_property_type: int = 10
    weight_beds_baths: int = 5

    # Price partial-credit (Req 4.2, 4.4): a price within 10% of the violated
    # bound earns `price_partial_points`; otherwise 0.
    price_near_band_pct: float = 0.10
    price_partial_points: int = 10

    # ARV% partial-credit (Req 5.5, 5.6): a Deal_ARV_Pct exceeding the ceiling
    # by no more than `arv_near_band_pp` percentage points earns
    # `arv_partial_points`; beyond that, 0.
    arv_near_band_pp: float = 5.00
    arv_partial_points: int = 7
    # Deal_ARV_Pct = round_half_up(price / arv * 100, arv_round_decimals) (Req 5.1).
    arv_round_decimals: int = 2

    # Hard-filter cap (Req 2.9): when the Market or Property_Type component
    # scores 0, the total score is capped at this value.
    hard_filter_cap: int = 25

    # Final score bounds (Req 2.3).
    score_min: int = 0
    score_max: int = 100

    # Strategy mapping and the wholesale-fits-any rule (Req 3.1-3.4).
    strategy_by_condition: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: _STRATEGY_BY_CONDITION
    )
    wholesale_fits_any: bool = True

    def __post_init__(self) -> None:
        total = (
            self.weight_market
            + self.weight_strategy
            + self.weight_price
            + self.weight_arv
            + self.weight_property_type
            + self.weight_beds_baths
        )
        if total != 100:
            raise ValueError(
                f"Scoring weights must sum to 100, got {total}"
            )

    def suitable_strategies(self, condition: str | None) -> tuple[str, ...]:
        """Return the strategies suited to a given property condition.

        Returns an empty tuple for null/unknown conditions. `wholesale` is not
        included here because it suits any condition (see `wholesale_fits_any`).
        """
        if condition is None:
            return ()
        return self.strategy_by_condition.get(condition, ())


#: The single Scoring_Config instance the Scoring_Engine reads from (Req 2.2).
SCORING_CONFIG = ScoringConfig()
