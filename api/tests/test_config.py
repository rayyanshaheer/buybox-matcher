"""Unit tests for api.config (Req 2.2, 14.3, 14.4)."""

import pytest

from api.config import (
    PROVIDER_KEY_VAR,
    SCORING_CONFIG,
    ConfigError,
    ScoringConfig,
    Settings,
    load_settings,
    validate_config,
)


# --------------------------------------------------------------------------- #
# Environment loading (Req 14.3)
# --------------------------------------------------------------------------- #


def test_load_settings_reads_all_variables():
    env = {
        "AI_PROVIDER": "openai",
        "OPENAI_API_KEY": "sk-test",
        "ANTHROPIC_API_KEY": "an-test",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_KEY": "service-key",
        "ALLOWED_ORIGIN": "http://localhost:5173",
    }
    settings = load_settings(env)
    assert settings.ai_provider == "openai"
    assert settings.openai_api_key == "sk-test"
    assert settings.anthropic_api_key == "an-test"
    assert settings.supabase_url == "https://example.supabase.co"
    assert settings.supabase_key == "service-key"
    assert settings.allowed_origin == "http://localhost:5173"


def test_load_settings_missing_become_none():
    settings = load_settings({})
    assert settings.ai_provider is None
    assert settings.provider_api_key is None
    assert settings.supabase_url is None


def test_provider_api_key_selects_by_provider():
    openai = Settings(ai_provider="openai", openai_api_key="sk", anthropic_api_key="an")
    anthropic = Settings(ai_provider="anthropic", openai_api_key="sk", anthropic_api_key="an")
    assert openai.provider_api_key == "sk"
    assert anthropic.provider_api_key == "an"


def test_import_does_not_require_env():
    # Constructing settings from an empty env must never raise.
    load_settings({})


# --------------------------------------------------------------------------- #
# Startup validation (Req 14.4)
# --------------------------------------------------------------------------- #


def _full_env():
    return {
        "AI_PROVIDER": "openai",
        "OPENAI_API_KEY": "sk-test",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_KEY": "service-key",
    }


def test_validate_config_passes_with_all_required():
    settings = validate_config(load_settings(_full_env()))
    assert settings.ai_provider == "openai"


def test_validate_config_passes_for_anthropic():
    env = {
        "AI_PROVIDER": "anthropic",
        "ANTHROPIC_API_KEY": "an-test",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_KEY": "service-key",
    }
    validate_config(load_settings(env))


@pytest.mark.parametrize(
    "drop_key,expected_var",
    [
        ("AI_PROVIDER", "AI_PROVIDER"),
        ("OPENAI_API_KEY", "OPENAI_API_KEY"),
        ("SUPABASE_URL", "SUPABASE_URL"),
        ("SUPABASE_KEY", "SUPABASE_KEY"),
    ],
)
def test_validate_config_names_missing_variable(drop_key, expected_var):
    env = _full_env()
    del env[drop_key]
    with pytest.raises(ConfigError) as exc:
        validate_config(load_settings(env))
    assert expected_var in str(exc.value)


def test_validate_config_treats_empty_as_missing():
    env = _full_env()
    env["SUPABASE_KEY"] = "   "
    with pytest.raises(ConfigError) as exc:
        validate_config(load_settings(env))
    assert "SUPABASE_KEY" in str(exc.value)


def test_validate_config_does_not_leak_secret_value():
    env = _full_env()
    env["SUPABASE_KEY"] = ""  # missing
    env["SUPABASE_URL"] = "https://super-secret-url.supabase.co"
    with pytest.raises(ConfigError) as exc:
        validate_config(load_settings(env))
    message = str(exc.value)
    # The present-but-unrelated secret value must never appear in the error.
    assert "super-secret-url" not in message


def test_validate_config_rejects_unknown_provider_without_value():
    env = _full_env()
    env["AI_PROVIDER"] = "totally-secret-provider"
    with pytest.raises(ConfigError) as exc:
        validate_config(load_settings(env))
    assert "totally-secret-provider" not in str(exc.value)


def test_validate_config_reports_selected_provider_key_only():
    # With provider=anthropic, a present OPENAI key is irrelevant; the
    # ANTHROPIC key is the one that must be reported as missing.
    env = {
        "AI_PROVIDER": "anthropic",
        "OPENAI_API_KEY": "sk-present",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_KEY": "service-key",
    }
    with pytest.raises(ConfigError) as exc:
        validate_config(load_settings(env))
    assert "ANTHROPIC_API_KEY" in str(exc.value)
    assert "OPENAI_API_KEY" not in str(exc.value)


# --------------------------------------------------------------------------- #
# Scoring_Config (Req 2.2)
# --------------------------------------------------------------------------- #


def test_scoring_weights_sum_to_100():
    c = SCORING_CONFIG
    total = (
        c.weight_market
        + c.weight_strategy
        + c.weight_price
        + c.weight_arv
        + c.weight_property_type
        + c.weight_beds_baths
    )
    assert total == 100


def test_scoring_weight_values():
    c = SCORING_CONFIG
    assert c.weight_market == 30
    assert c.weight_strategy == 20
    assert c.weight_price == 20
    assert c.weight_arv == 15
    assert c.weight_property_type == 10
    assert c.weight_beds_baths == 5


def test_scoring_thresholds():
    c = SCORING_CONFIG
    assert c.price_near_band_pct == 0.10
    assert c.price_partial_points == 10
    assert c.arv_near_band_pp == 5.00
    assert c.arv_partial_points == 7
    assert c.arv_round_decimals == 2
    assert c.hard_filter_cap == 25
    assert c.score_min == 0
    assert c.score_max == 100


def test_strategy_mapping():
    c = SCORING_CONFIG
    assert c.suitable_strategies("distressed") == ("fix_and_flip", "brrrr")
    assert c.suitable_strategies("light_rehab") == ("fix_and_flip", "brrrr")
    assert c.suitable_strategies("turnkey") == ("buy_and_hold",)
    assert c.suitable_strategies(None) == ()
    assert c.suitable_strategies("unknown") == ()
    assert c.wholesale_fits_any is True


def test_scoring_config_rejects_bad_weight_sum():
    with pytest.raises(ValueError):
        ScoringConfig(weight_market=99)


def test_scoring_config_is_frozen():
    with pytest.raises(Exception):
        SCORING_CONFIG.weight_market = 999  # type: ignore[misc]


def test_provider_key_var_mapping():
    assert PROVIDER_KEY_VAR["openai"] == "OPENAI_API_KEY"
    assert PROVIDER_KEY_VAR["anthropic"] == "ANTHROPIC_API_KEY"
