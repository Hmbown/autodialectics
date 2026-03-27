"""
OpenAI-compatible API gateway that routes through the Claude CLI.

Exposes an aiohttp server with endpoints:
- POST /v1/chat/completions  — OpenAI Chat Completions format
- GET  /v1/models            — lists available Claude models
- GET  /health               — health check

Works with any Claude Code auth method (OAuth, API key, etc.)
by delegating to `claude -p` which handles credential resolution.

Follows the same adapter pattern as hermesagent/gateway/platforms/api_server.py.

Start standalone:
    uv run python -m autodialectics.routing.claude_gateway
    # Listens on http://127.0.0.1:8642

Environment variables:
    CLAUDE_GATEWAY_HOST  — bind address  (default: 127.0.0.1)
    CLAUDE_GATEWAY_PORT  — listen port   (default: 8642)
    CLAUDE_GATEWAY_KEY   — bearer token  (default: none / open)
    CLAUDE_GATEWAY_MODEL — claude model   (default: sonnet)
"""

from __future__ import annotations

import asyncio
import argparse
import json
import logging
import os
import sys
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8642
DEFAULT_MODEL = "sonnet"

# Model alias map — what callers send → what claude CLI expects
_MODEL_MAP: dict[str, str] = {
    "default": "sonnet",
    "claude-sonnet": "sonnet",
    "claude-opus": "opus",
    "claude-haiku": "haiku",
    "sonnet": "sonnet",
    "opus": "opus",
    "haiku": "haiku",
}

app = FastAPI(title="Claude CLI Gateway")


def _get_api_key() -> str:
    return os.getenv("CLAUDE_GATEWAY_KEY", "")


def _get_default_model() -> str:
    return os.getenv("CLAUDE_GATEWAY_MODEL", DEFAULT_MODEL)


def _check_auth(request: Request) -> None:
    """Validate bearer token if configured."""
    api_key = _get_api_key()
    if not api_key:
        return
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:].strip() == api_key:
        return
    raise HTTPException(status_code=401, detail="Invalid API key")


def _resolve_model(requested: str) -> str:
    """Map an incoming model name to a claude CLI model flag."""
    default = _get_default_model()
    if not requested or requested == "default":
        return _MODEL_MAP.get(default, default)
    return _MODEL_MAP.get(requested.lower(), requested)


def _messages_to_prompt(messages: list[dict[str, Any]]) -> tuple[str, str]:
    """Convert OpenAI messages array to (system_prompt, user_prompt)."""
    system_parts: list[str] = []
    user_parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            system_parts.append(content)
        elif role == "user":
            user_parts.append(content)
        elif role == "assistant":
            # Include prior assistant turns as context
            user_parts.append(f"[Previous assistant response]: {content}")
    return "\n\n".join(system_parts), "\n\n".join(user_parts)


def _parse_runtime_options(argv: list[str]) -> argparse.Namespace:
    """Parse optional runtime flags for the standalone gateway."""
    parser = argparse.ArgumentParser(prog="claude-gateway")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--model")
    parser.add_argument("--api-key")
    return parser.parse_args(argv)


async def _call_claude(
    system_prompt: str,
    user_prompt: str,
    model: str,
) -> dict[str, Any]:
    """Call claude CLI as a subprocess and return parsed JSON result."""
    cmd = ["claude", "-p", "--output-format", "json", "--model", model]

    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])

    full_input = user_prompt

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input=full_input.encode()),
        timeout=300,
    )

    if proc.returncode != 0:
        err_text = stderr.decode(errors="replace")[:500]
        # Try to parse structured error from stdout (claude outputs JSON even on failure)
        try:
            result = json.loads(stdout.decode())
            if result.get("is_error"):
                raise RuntimeError(
                    f"claude CLI error: {result.get('result', err_text)}"
                )
        except (json.JSONDecodeError, KeyError):
            pass
        raise RuntimeError(f"claude CLI exited {proc.returncode}: {err_text}")

    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError:
        return {"result": stdout.decode().strip()}


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "platform": "claude-gateway"})


@app.get("/v1/models")
async def list_models(request: Request) -> JSONResponse:
    _check_auth(request)
    return JSONResponse({
        "object": "list",
        "data": [
            {"id": f"claude-{m}", "object": "model", "created": int(time.time()),
             "owned_by": "anthropic"}
            for m in ("sonnet", "opus", "haiku")
        ],
    })


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    _check_auth(request)

    body = await request.json()
    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        raise HTTPException(400, "Missing or invalid 'messages' field")

    model = _resolve_model(body.get("model", ""))
    system_prompt, user_prompt = _messages_to_prompt(messages)

    if not user_prompt:
        raise HTTPException(400, "No user message found")

    start = time.time()
    try:
        cli_result = await _call_claude(system_prompt, user_prompt, model)
    except (RuntimeError, asyncio.TimeoutError) as exc:
        raise HTTPException(502, f"Claude backend error: {exc}")

    elapsed_ms = int((time.time() - start) * 1000)

    content = cli_result.get("result", "")
    usage_raw = cli_result.get("usage", {})

    input_tokens = usage_raw.get("input_tokens", 0)
    output_tokens = usage_raw.get("output_tokens", 0)
    cache_creation = usage_raw.get("cache_creation_input_tokens", 0)
    cache_read = usage_raw.get("cache_read_input_tokens", 0)

    return JSONResponse({
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": f"claude-{model}",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": input_tokens + cache_creation + cache_read,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + cache_creation + cache_read + output_tokens,
        },
        "_claude_meta": {
            "duration_ms": elapsed_ms,
            "cost_usd": cli_result.get("total_cost_usd"),
            "stop_reason": cli_result.get("stop_reason"),
            "cache_creation_tokens": cache_creation,
            "cache_read_tokens": cache_read,
        },
    })


def main() -> None:
    options = _parse_runtime_options(sys.argv[1:])

    if options.host:
        os.environ["CLAUDE_GATEWAY_HOST"] = options.host
    if options.port is not None:
        os.environ["CLAUDE_GATEWAY_PORT"] = str(options.port)
    if options.model:
        os.environ["CLAUDE_GATEWAY_MODEL"] = options.model
    if options.api_key:
        os.environ["CLAUDE_GATEWAY_KEY"] = options.api_key

    host = os.getenv("CLAUDE_GATEWAY_HOST", DEFAULT_HOST)
    port = int(os.getenv("CLAUDE_GATEWAY_PORT", str(DEFAULT_PORT)))
    print(f"Claude CLI gateway starting on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
