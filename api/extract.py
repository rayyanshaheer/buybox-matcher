"""Extraction_Service: the only AI call on the write path (design: ``api/extract.py``).

This module turns arbitrary investor prose into a strict-schema Buy_Box, or
fails cleanly. It owns three things (design "AI Extraction Design"):

1. **A thin, provider-agnostic adapter** exposing a single method,
   ``complete_json(system, user) -> str``, selected by ``AI_PROVIDER``
   (``openai`` | ``anthropic``). The provider SDKs are imported *lazily*
   inside each adapter so importing this module never requires the SDKs to be
   installed (mirrors the lazy-client pattern in ``api/db.py``). Where the
   provider supports it, JSON / structured-output mode is enabled to constrain
   the response (design "System Prompt Strategy").

2. **The strict-JSON system prompt** enumerating the nine Buy_Box fields, the
   allowed enum vocabularies, and the null-for-absent rule (Req 1.2-1.6).

3. **The extraction pipeline** :func:`extract_buy_box`: call the provider with
   a 30-second timeout (Req 1.9), ``json.loads`` the result, then coerce and
   validate via :class:`api.models.BuyBoxModel` (Req 1.1, 1.3-1.6). Any
   timeout, provider/transport error, unparseable output, or validation
   failure raises :class:`ExtractionError` so the route persists nothing
   (Req 1.7, 1.9).

**Testability seam.** The provider call is injectable: :func:`extract_buy_box`
accepts an optional ``provider`` callable with the signature
``(system: str, user: str) -> str``. When omitted it falls back to the
module-level provider resolved from configuration. Task 6.5 can therefore unit
test the whole pipeline with a mock provider and **no live API calls**.
"""

from __future__ import annotations

import json
from typing import Callable, Protocol, runtime_checkable

from pydantic import ValidationError

from api.config import Settings, load_settings
from api.models import BuyBoxModel

# --------------------------------------------------------------------------- #
# Tunables (design "Timeout & Failure Handling", Req 1.9)
# --------------------------------------------------------------------------- #

#: Hard ceiling on the provider call. A timeout raises :class:`ExtractionError`
#: and the route persists nothing (Req 1.9).
EXTRACTION_TIMEOUT_SECONDS: float = 30.0

#: The signature of an injectable provider call: ``(system, user) -> raw json``.
ProviderCallable = Callable[[str, str], str]


# --------------------------------------------------------------------------- #
# Failure type (design flowchart: every failure path -> ExtractionError)
# --------------------------------------------------------------------------- #


class ExtractionError(RuntimeError):
    """Raised when extraction cannot produce a valid Buy_Box.

    Covers every failure path on the extraction write path (Req 1.7, 1.9):
    a provider/transport error, a timeout, output that is not valid JSON
    (``json.JSONDecodeError``), and output that fails Buy_Box coercion /
    enum / range validation. The route maps this to an error status and
    **persists nothing**.

    ``kind`` categorizes the failure so the route (task 6.2) can choose the
    right HTTP status without re-inspecting the cause:

    - ``"provider"`` / ``"timeout"`` — extraction failed talking to the
      AI_Provider; map to an error status (Req 1.9).
    - ``"parse"`` — output was not valid JSON; map to 422 (Req 1.7, 10.2).
    - ``"validation"`` — output was valid JSON but failed Buy_Box coercion,
      enum, or price-range validation; map to 422 (Req 1.10, 10.2). The
      originating ``pydantic.ValidationError`` is preserved as ``__cause__``.
    """

    def __init__(self, message: str, *, kind: str = "provider") -> None:
        super().__init__(message)
        self.kind = kind


# --------------------------------------------------------------------------- #
# Strict-JSON system prompt (design "System Prompt Strategy", Req 1.2-1.6)
# --------------------------------------------------------------------------- #

#: Allowed enum vocabularies, kept in one place so the prompt and any future
#: validation stay in lockstep with ``api/models.py`` (Req 1.4-1.6).
_STRATEGY_VALUES = ("fix_and_flip", "buy_and_hold", "brrrr", "wholesale")
_PROPERTY_TYPE_VALUES = ("single_family", "multi_family", "condo", "land")
_CONDITION_VALUES = ("distressed", "light_rehab", "turnkey", "any")


def build_system_prompt() -> str:
    """Return the strict-JSON extraction system prompt (Req 1.2-1.6).

    The prompt pins the model to one job and one output format: a single JSON
    object with the nine Buy_Box fields, drawn from the allowed enum
    vocabularies, with absent fields set to ``null`` and never inferred.
    """
    strategy = ", ".join(_STRATEGY_VALUES)
    property_type = ", ".join(_PROPERTY_TYPE_VALUES)
    condition = ", ".join(_CONDITION_VALUES)

    return f"""\
You extract a real-estate investor's purchase criteria ("buy box") from a free-text message.

Output MUST be a single JSON object and nothing else: no prose, no explanation, no markdown code fences. Output exactly these nine fields:

- "markets": array of city/metro name strings (e.g. ["Tampa", "Orlando"]). Use [] only if explicitly none; otherwise null when not mentioned.
- "strategy": one of [{strategy}], or null.
- "property_type": one of [{property_type}], or null.
- "price_min": integer US dollars, or null.
- "price_max": integer US dollars, or null.
- "arv_pct_max": integer percent (0-100), or null.
- "min_beds": integer, or null.
- "min_baths": number, or null.
- "condition": one of [{condition}], or null.

Rules:
1. NULL-FOR-ABSENT: If a field is not clearly stated in the message, set it to null. Do NOT infer, guess, or fill in defaults for values that are not present.
2. Use ONLY the allowed enum values listed above for "strategy", "property_type", and "condition". If the message does not clearly indicate one of those exact values, use null.
3. Strip currency symbols, commas, and the letter "k"/"m" shorthand and convert prices to plain integers (e.g. "$250k" -> 250000).
4. "arv_pct_max" is the maximum purchase-price-to-ARV percentage the buyer accepts, as an integer (e.g. "buy at 70% of ARV" -> 70).

Example message: "Looking for distressed single family homes in Tampa or Lakeland, up to 250k, max 70% ARV, at least 3 beds. Fix and flip."
Example output: {{"markets": ["Tampa", "Lakeland"], "strategy": "fix_and_flip", "property_type": "single_family", "price_min": null, "price_max": 250000, "arv_pct_max": 70, "min_beds": 3, "min_baths": null, "condition": "distressed"}}

Example message: "Cash buyer, turnkey rentals only."
Example output: {{"markets": null, "strategy": "buy_and_hold", "property_type": null, "price_min": null, "price_max": null, "arv_pct_max": null, "min_beds": null, "min_baths": null, "condition": "turnkey"}}"""


# --------------------------------------------------------------------------- #
# Provider adapter (design "Provider Selection")
# --------------------------------------------------------------------------- #


@runtime_checkable
class Provider(Protocol):
    """A provider-agnostic completion interface.

    One method only, so :func:`extract_buy_box` never depends on a concrete
    SDK (design "Provider Selection").
    """

    def complete_json(self, system: str, user: str) -> str:
        """Return the model's raw response text (expected to be JSON)."""
        ...


class OpenAIProvider:
    """OpenAI adapter. Imports the ``openai`` SDK lazily on first call.

    Enables JSON output mode via ``response_format={"type": "json_object"}``
    so the model is constrained to emit a single JSON object
    (design "System Prompt Strategy").
    """

    def __init__(self, api_key: str, *, model: str = "gpt-4o-mini") -> None:
        self._api_key = api_key
        self._model = model

    def complete_json(self, system: str, user: str) -> str:
        try:
            from openai import OpenAI  # imported lazily on purpose
        except ImportError as exc:  # pragma: no cover - depends on install env
            raise ExtractionError(
                "The 'openai' package is required for the configured provider "
                "but is not installed."
            ) from exc

        # The SDK applies its own per-request timeout; we also wrap the whole
        # call in a hard timeout in `extract_buy_box` (Req 1.9).
        client = OpenAI(api_key=self._api_key, timeout=EXTRACTION_TIMEOUT_SECONDS)
        response = client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content
        return content or ""


class AnthropicProvider:
    """Anthropic adapter. Imports the ``anthropic`` SDK lazily on first call.

    Anthropic has no JSON response-format flag; the strict-JSON system prompt
    plus a pre-filled assistant turn ("{{") nudges a bare JSON object. The
    leading brace is re-attached to the returned text before parsing.
    """

    def __init__(
        self, api_key: str, *, model: str = "claude-3-5-sonnet-latest"
    ) -> None:
        self._api_key = api_key
        self._model = model

    def complete_json(self, system: str, user: str) -> str:
        try:
            import anthropic  # imported lazily on purpose
        except ImportError as exc:  # pragma: no cover - depends on install env
            raise ExtractionError(
                "The 'anthropic' package is required for the configured "
                "provider but is not installed."
            ) from exc

        client = anthropic.Anthropic(
            api_key=self._api_key, timeout=EXTRACTION_TIMEOUT_SECONDS
        )
        message = client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # Concatenate any text blocks the SDK returns.
        parts = [
            getattr(block, "text", "") for block in getattr(message, "content", [])
        ]
        return "".join(parts)


def build_provider(
    settings: Settings | None = None,
    *,
    user_api_key: str | None = None,
) -> Provider:
    """Construct the provider selected by ``AI_PROVIDER`` (design "Provider Selection").

    Reads configuration via :func:`api.config.load_settings` when ``settings``
    is not supplied. Raises :class:`ExtractionError` when the provider is
    unconfigured/unsupported or its API key is missing — extraction cannot run
    without a usable provider.

    When ``user_api_key`` is provided (BYOK mode), it overrides the server-side
    key for this single call. The provider selection (openai/anthropic) still
    comes from the server config or defaults to "openai" if unset.
    """
    resolved = settings if settings is not None else load_settings()
    provider = (resolved.ai_provider or "openai").strip().lower()

    # Use the user-supplied key if provided, otherwise fall back to server key.
    api_key = user_api_key if user_api_key else resolved.provider_api_key

    if provider not in ("openai", "anthropic"):
        raise ExtractionError(
            "AI_PROVIDER is not configured to a supported provider "
            "(expected 'openai' or 'anthropic')."
        )
    if not (api_key or "").strip():
        raise ExtractionError(
            "No API key available. Please provide your OpenAI API key in Settings.",
            kind="provider",
        )

    if provider == "openai":
        return OpenAIProvider(api_key)
    return AnthropicProvider(api_key)


def _default_provider_call(system: str, user: str) -> str:
    """Module-level provider seam used when no provider is injected.

    Builds the configured provider lazily per call so importing this module
    never touches configuration or the network. Tests inject their own
    callable and never reach this path.
    """
    return build_provider().complete_json(system, user)


# --------------------------------------------------------------------------- #
# Extraction pipeline (design flowchart, Req 1.1, 1.3-1.6, 1.9)
# --------------------------------------------------------------------------- #


def _call_with_timeout(
    provider: ProviderCallable, system: str, user: str, timeout: float
) -> str:
    """Run ``provider(system, user)`` under a hard ``timeout`` (Req 1.9).

    Executes the (blocking) provider call on a worker thread and waits at most
    ``timeout`` seconds. A timeout raises :class:`ExtractionError`; the worker
    is left to unwind on its own. Any exception raised by the provider is
    re-raised to the caller for translation.
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(provider, system, user)
        try:
            return future.result(timeout=timeout)
        except FutureTimeout as exc:
            future.cancel()
            raise ExtractionError(
                f"AI provider did not respond within {timeout:.0f} seconds.",
                kind="timeout",
            ) from exc
    finally:
        # Do not block shutdown on a still-running worker after a timeout.
        executor.shutdown(wait=False)


def extract_buy_box(
    raw_text: str,
    *,
    provider: ProviderCallable | None = None,
    timeout: float = EXTRACTION_TIMEOUT_SECONDS,
) -> BuyBoxModel:
    """Extract a validated Buy_Box from ``raw_text`` (Req 1.1, 1.3-1.6, 1.9).

    Pipeline (design "Parsing, Coercion, Validation"):

    1. Call the provider with the strict-JSON system prompt under a 30s
       timeout (Req 1.1, 1.9).
    2. ``json.loads`` the response (Req 1.7 -> unparseable raises here).
    3. Coerce / enum-validate / range-validate via :class:`BuyBoxModel`
       (Req 1.2-1.6, 1.10).

    The provider call is injectable for testing: pass ``provider`` as a
    callable ``(system, user) -> str``. When omitted, the configured
    module-level provider is used.

    Raises :class:`ExtractionError` on any provider/transport error, timeout,
    unparseable output, or validation failure so the caller persists nothing
    (Req 1.7, 1.9). The error's ``kind`` attribute (``"provider"``,
    ``"timeout"``, ``"parse"``, or ``"validation"``) lets the route choose the
    HTTP status: provider/timeout -> error status (Req 1.9); parse/validation
    -> 422 (Req 1.7, 1.10, 10.2). For validation failures the originating
    ``pydantic.ValidationError`` is preserved as ``__cause__``.
    """
    call: ProviderCallable = provider if provider is not None else _default_provider_call
    system = build_system_prompt()

    # 1. Provider call under a hard timeout. Provider/transport errors and
    #    timeouts both surface as ExtractionError (Req 1.9).
    try:
        raw_response = _call_with_timeout(call, system, raw_text, timeout)
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - any provider/transport failure
        raise ExtractionError(
            f"AI provider call failed: {exc}", kind="provider"
        ) from exc

    # 2. Parse the JSON. Unparseable output -> ExtractionError (Req 1.7).
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise ExtractionError(
            "AI provider returned output that is not valid JSON.", kind="parse"
        ) from exc

    if not isinstance(parsed, dict):
        raise ExtractionError(
            "AI provider returned JSON that is not an object.", kind="parse"
        )

    # 3. Coerce + enum/range validate. A ValidationError here means the model
    #    produced an out-of-vocabulary enum or an invalid price range; the
    #    route maps that to 422 (Req 1.10, 10.2). Surfaced as ExtractionError
    #    with kind="validation"; the ValidationError is preserved as __cause__.
    try:
        return BuyBoxModel.model_validate(parsed)
    except ValidationError as exc:
        raise ExtractionError(
            f"AI provider output failed Buy_Box validation: {exc}",
            kind="validation",
        ) from exc
