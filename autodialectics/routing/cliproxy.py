"""CLI proxy: OpenAI-compatible LLM client with offline fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_REQUEST_FAILURE_PREFIX = "[LLM REQUEST FAILED]"
_OFFLINE_PREFIX = "[OFFLINE MODE]"


def is_request_failure_response_text(content: str) -> bool:
    """Return True when content encodes an explicit upstream request failure."""
    return content.strip().startswith(_REQUEST_FAILURE_PREFIX)


def is_offline_response_text(content: str) -> bool:
    """Return True when content comes from the offline fallback client."""
    return content.strip().startswith(_OFFLINE_PREFIX)


@dataclass
class ModelResponse:
    """Response from the LLM."""

    content: str
    role: str = "assistant"
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)


class ModelClient:
    """OpenAI-compatible chat completions client.

    Supports any server that implements the /v1/chat/completions endpoint.
    Falls back to canned responses when offline.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        model: str = "default",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model or "default"
        self._timeout = 120.0

    @property
    def offline(self) -> bool:
        """True if no valid base_url is configured."""
        return not self.base_url or self.base_url.lower() == "offline"

    def complete(
        self,
        role: str,
        system_prompt: str,
        user_prompt: str,
        *,
        response_format: str | None = None,
    ) -> ModelResponse:
        """Send a chat completion request.

        Parameters
        ----------
        role : str
            Identifier for the calling component (e.g. 'planner', 'executor').
        system_prompt : str
            System message for the LLM.
        user_prompt : str
            User message for the LLM.
        response_format : str | None
            Optional response format hint (e.g. 'json').

        Returns
        -------
        ModelResponse
            The model's response.
        """
        if self.offline:
            return self._offline_response(role)

        url = f"{self.base_url}/v1/chat/completions"
        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
        }
        if response_format:
            payload["response_format"] = {"type": response_format}

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            content = ""
            model_name = ""
            usage = {}

            choices = data.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                content = message.get("content", "")
                model_name = data.get("model", "")

            usage = data.get("usage", {})

            logger.debug(
                "[%s] LLM response: %d chars, model=%s",
                role,
                len(content),
                model_name,
            )
            return ModelResponse(
                content=content,
                role="assistant",
                model=model_name,
                usage=usage,
            )

        except httpx.ConnectError as exc:
            logger.debug(
                "[%s] Connection failed to %s: %s", role, self.base_url, exc
            )
            return self._failure_response(
                role,
                reason=f"Connection to configured endpoint failed: {self.base_url}",
            )
        except httpx.HTTPStatusError as exc:
            logger.debug(
                "[%s] HTTP error from %s: %s %s",
                role,
                self.base_url,
                exc.response.status_code,
                exc.response.text[:200],
            )
            return self._failure_response(
                role,
                reason=(
                    f"Configured endpoint returned HTTP {exc.response.status_code}: "
                    f"{self.base_url}"
                ),
            )
        except Exception as exc:
            logger.debug(
                "[%s] Unexpected error calling LLM: %s", role, exc
            )
            return self._failure_response(
                role,
                reason=f"Configured endpoint request failed: {type(exc).__name__}",
            )

    @staticmethod
    def _offline_response(role: str) -> ModelResponse:
        """Return a canned response for offline mode."""
        return ModelResponse(
            content=(
                f"{_OFFLINE_PREFIX} No LLM endpoint configured. "
                f"Role: {role}. "
                f"The system is operating in heuristic-only mode."
            ),
            role="assistant",
        )

    @staticmethod
    def _failure_response(role: str, reason: str) -> ModelResponse:
        """Return an explicit request-failure response for a configured endpoint."""
        return ModelResponse(
            content=(
                f"{_REQUEST_FAILURE_PREFIX} {reason}. "
                f"Role: {role}. "
                f"The system fell back because the configured endpoint did not "
                f"produce a usable response."
            ),
            role="assistant",
        )


class OfflineModelClient(ModelClient):
    """A ModelClient that always returns offline responses."""

    def __init__(self) -> None:
        super().__init__(base_url="offline", model="offline")

    @property
    def offline(self) -> bool:
        return True

    def complete(
        self,
        role: str,
        system_prompt: str,
        user_prompt: str,
        *,
        response_format: str | None = None,
    ) -> ModelResponse:
        return self._offline_response(role)


def build_model_client(settings: Any) -> ModelClient:
    """Build a ModelClient from application settings.

    Parameters
    ----------
    settings : Settings
        Application settings with cliproxy_base_url and cliproxy_api_key.

    Returns
    -------
    ModelClient
        OfflineModelClient if no base_url configured, otherwise ModelClient.
    """
    base_url = getattr(settings, "cliproxy_base_url", "")
    api_key = getattr(settings, "cliproxy_api_key", "")
    model = getattr(settings, "cliproxy_model", "default")

    if not base_url:
        logger.info("No cliproxy_base_url configured; using offline client")
        return OfflineModelClient()

    return ModelClient(base_url=base_url, api_key=api_key, model=model)
