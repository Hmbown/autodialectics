"""
OpenAI-compatible API gateway that dispatches to the active local CLI.

Provider selection:
- auto   -> prefer the CLI indicated by the current environment
- codex  -> route via `codex exec`
- claude -> route via `claude -p`
- hermes -> route via `hermes chat -q -Q`
"""

from __future__ import annotations

import asyncio
import argparse
import logging
import os
import shutil
import sys
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

from autodialectics.routing.claude_gateway import _call_claude
from autodialectics.routing.codex_gateway import _call_codex

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8644
DEFAULT_PROVIDER = "auto"
_SUPPORTED_PROVIDERS = ("auto", "codex", "claude", "hermes")

app = FastAPI(title="CLI Gateway")


def _get_api_key() -> str:
    return os.getenv("CLI_GATEWAY_KEY", "")


def _check_auth(request: Request) -> None:
    api_key = _get_api_key()
    if not api_key:
        return
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:].strip() == api_key:
        return
    raise HTTPException(status_code=401, detail="Invalid API key")


def _preferred_provider() -> str:
    requested = os.getenv("CLI_GATEWAY_PROVIDER", DEFAULT_PROVIDER).strip().lower()
    return requested if requested in _SUPPORTED_PROVIDERS else DEFAULT_PROVIDER


def _available_provider_commands() -> dict[str, bool]:
    return {
        "codex": shutil.which("codex") is not None,
        "claude": shutil.which("claude") is not None,
        "hermes": shutil.which("hermes") is not None,
    }


def _detect_provider() -> str:
    """Detect the active local CLI, falling back to the first available provider."""
    available = _available_provider_commands()

    if os.getenv("CODEX_THREAD_ID") and available["codex"]:
        return "codex"

    if any(
        os.getenv(name)
        for name in (
            "CLAUDECODE",
            "CLAUDE_CODE_SIMPLE",
            "ANTHROPIC_API_KEY",
        )
    ) and available["claude"]:
        return "claude"

    if any(
        os.getenv(name)
        for name in (
            "HERMES_SESSION_ID",
            "HERMES_PROVIDER",
            "HERMES_MODEL",
        )
    ) and available["hermes"]:
        return "hermes"

    for candidate in ("codex", "claude", "hermes"):
        if available[candidate]:
            return candidate

    raise RuntimeError("No supported local CLI was found on PATH.")


def _resolve_provider() -> str:
    provider = _preferred_provider()
    if provider == "auto":
        return _detect_provider()
    return provider


def _default_model_for_provider(provider: str) -> str:
    configured = os.getenv("CLI_GATEWAY_MODEL", "").strip()
    if configured:
        return configured
    if provider == "codex":
        return os.getenv("CODEX_GATEWAY_MODEL", "").strip() or "gpt-5.4-mini"
    if provider == "claude":
        return os.getenv("CLAUDE_GATEWAY_MODEL", "").strip() or "sonnet"
    return os.getenv("HERMES_GATEWAY_MODEL", "").strip() or "auto"


def _resolve_model(provider: str, requested: str) -> str:
    normalized = requested.strip().lower()
    if not normalized or normalized in {"default", "auto"}:
        return _default_model_for_provider(provider)
    return requested


def _parse_runtime_options(argv: list[str]) -> argparse.Namespace:
    """Parse optional runtime flags for the standalone gateway."""
    parser = argparse.ArgumentParser(prog="cli-gateway")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--provider", choices=_SUPPORTED_PROVIDERS)
    parser.add_argument("--model")
    parser.add_argument("--api-key")
    return parser.parse_args(argv)


def _messages_to_prompt(messages: list[dict[str, Any]]) -> tuple[str, str]:
    system_parts: list[str] = []
    user_parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )

        if role == "system":
            system_parts.append(str(content))
        elif role == "user":
            user_parts.append(str(content))
        elif role == "assistant":
            user_parts.append(f"[Previous assistant response]: {content}")
    return "\n\n".join(system_parts).strip(), "\n\n".join(user_parts).strip()


async def _call_hermes(
    system_prompt: str,
    user_prompt: str,
    model: str,
) -> dict[str, Any]:
    import json

    prompt = user_prompt
    if system_prompt:
        prompt = f"System instructions:\n{system_prompt}\n\nUser request:\n{user_prompt}"

    cmd = ["hermes", "chat", "-q", prompt, "-Q"]
    if model:
        cmd.extend(["-m", model])

    provider = os.getenv("HERMES_GATEWAY_PROVIDER", "").strip()
    if provider:
        cmd.extend(["--provider", provider])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    stdout_text = stdout.decode(errors="replace").strip()
    stderr_text = stderr.decode(errors="replace").strip()

    if proc.returncode != 0:
        err_excerpt = (stderr_text or stdout_text)[-1200:]
        raise RuntimeError(f"hermes chat exited {proc.returncode}: {err_excerpt}")

    if not stdout_text:
        raise RuntimeError("Hermes CLI did not emit a final response.")

    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    try:
        parsed = json.loads(stdout_text)
        if isinstance(parsed, dict) and parsed.get("response"):
            stdout_text = str(parsed["response"]).strip()
    except json.JSONDecodeError:
        pass

    return {"result": stdout_text, "usage": usage}


async def _call_provider(
    provider: str,
    system_prompt: str,
    user_prompt: str,
    model: str,
) -> dict[str, Any]:
    if provider == "codex":
        return await _call_codex(system_prompt, user_prompt, model)
    if provider == "claude":
        return await _call_claude(system_prompt, user_prompt, model)
    if provider == "hermes":
        return await _call_hermes(system_prompt, user_prompt, model)
    raise RuntimeError(f"Unsupported CLI provider: {provider}")


@app.get("/health")
async def health() -> JSONResponse:
    provider = _resolve_provider()
    return JSONResponse({"status": "ok", "platform": "cli-gateway", "provider": provider})


@app.get("/v1/models")
async def list_models(request: Request) -> JSONResponse:
    _check_auth(request)
    provider = _resolve_provider()
    default_model = _default_model_for_provider(provider)
    return JSONResponse(
        {
            "object": "list",
            "data": [
                {
                    "id": default_model,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": provider,
                }
            ],
        }
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    _check_auth(request)

    body = await request.json()
    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        raise HTTPException(400, "Missing or invalid 'messages' field")

    provider = _resolve_provider()
    model = _resolve_model(provider, str(body.get("model") or ""))

    system_prompt, user_prompt = _messages_to_prompt(messages)
    if not user_prompt:
        raise HTTPException(400, "No user message found")

    start = time.time()
    try:
        provider_result = await _call_provider(provider, system_prompt, user_prompt, model)
    except (RuntimeError, asyncio.TimeoutError) as exc:
        raise HTTPException(502, f"{provider} backend error: {exc}")

    elapsed_ms = int((time.time() - start) * 1000)
    content = provider_result.get("result", "")
    usage = provider_result.get(
        "usage",
        {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    )

    return JSONResponse(
        {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
            "_cli_meta": {
                "duration_ms": elapsed_ms,
                "provider": provider,
            },
        }
    )


def main() -> None:
    options = _parse_runtime_options(sys.argv[1:])

    if options.host:
        os.environ["CLI_GATEWAY_HOST"] = options.host
    if options.port is not None:
        os.environ["CLI_GATEWAY_PORT"] = str(options.port)
    if options.provider:
        os.environ["CLI_GATEWAY_PROVIDER"] = options.provider
    if options.model:
        os.environ["CLI_GATEWAY_MODEL"] = options.model
    if options.api_key:
        os.environ["CLI_GATEWAY_KEY"] = options.api_key

    host = os.getenv("CLI_GATEWAY_HOST", DEFAULT_HOST)
    port = int(os.getenv("CLI_GATEWAY_PORT", str(DEFAULT_PORT)))
    provider = _resolve_provider()
    print(f"CLI gateway starting on http://{host}:{port} using provider={provider}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
