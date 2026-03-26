"""Helpers for configuring DSPy against the configured OpenAI-compatible endpoint."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


def _normalize_api_base(base_url: str) -> str:
    base = base_url.rstrip("/")
    if not base:
        raise ValueError("No DSPy-compatible API base URL is configured.")
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def _resolve_model_name(settings: Any) -> str:
    model = (
        getattr(settings, "cliproxy_model", "")
        or "default"
    ).strip()
    if "/" in model:
        return model
    return f"openai/{model}"


def build_dspy_lm(settings: Any, **kwargs: Any):
    """Build a DSPy LM from repo settings."""
    import dspy  # type: ignore[import-untyped]

    base_url = getattr(settings, "dspy_api_base", None) or getattr(
        settings, "cliproxy_base_url", ""
    )
    api_key = (
        getattr(settings, "dspy_api_key", None)
        or getattr(settings, "cliproxy_api_key", "")
        or "EMPTY"
    )

    return dspy.LM(
        model=_resolve_model_name(settings),
        api_base=_normalize_api_base(base_url),
        api_key=api_key,
        **kwargs,
    )


@contextmanager
def dspy_lm_context(
    settings: Any,
    **kwargs: Any,
) -> Iterator[tuple[Any, Any]]:
    """Yield `(dspy, lm)` with the configured LM bound in a DSPy context."""
    import dspy  # type: ignore[import-untyped]

    lm = build_dspy_lm(settings, **kwargs)
    with dspy.context(lm=lm):
        yield dspy, lm
