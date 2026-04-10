"""
OpenAI-compatible API gateway that routes through the Codex CLI.

Exposes:
- POST /v1/chat/completions
- GET  /v1/models
- GET  /health

This lets Autodialectics use `codex exec` as a local CLI-to-HTTP proxy backend.
"""

from __future__ import annotations

import asyncio
import argparse
import json
import logging
import os
import shlex
import sys
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8642
DEFAULT_MODEL = "gpt-5.4"
DEFAULT_TIMEOUT_SECONDS = 300

app = FastAPI(title="Codex CLI Gateway")


def _get_api_key() -> str:
    return os.getenv("CODEX_GATEWAY_KEY", "")


def _get_default_model() -> str:
    return os.getenv("CODEX_GATEWAY_MODEL", DEFAULT_MODEL)


def _resolve_model(requested: str) -> str:
    """Map placeholder model values to an actual Codex model name."""
    if not requested or requested.strip().lower() == "default":
        return _get_default_model()
    return requested


def _get_timeout_seconds() -> int:
    raw = os.getenv("CODEX_GATEWAY_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _check_auth(request: Request) -> None:
    """Validate bearer token if configured."""
    api_key = _get_api_key()
    if not api_key:
        return
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and auth[7:].strip() == api_key:
        return
    raise HTTPException(status_code=401, detail="Invalid API key")


def _messages_to_prompt(messages: list[dict[str, Any]]) -> tuple[str, str]:
    """Convert OpenAI chat messages to a Codex-friendly system and user prompt."""
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


def _build_codex_prompt(system_prompt: str, user_prompt: str) -> str:
    """Combine prompts into one string suitable for `codex exec`."""
    if system_prompt:
        return (
            "System instructions:\n"
            f"{system_prompt}\n\n"
            "User request:\n"
            f"{user_prompt}"
        )
    return user_prompt


def _extract_codex_response(stdout: str) -> tuple[str, dict[str, int]]:
    """Parse `codex exec --json` output and return final text plus usage."""
    content_parts: list[str] = []
    usage: dict[str, int] = {}

    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue

        if payload.get("type") == "item.completed":
            item = payload.get("item", {})
            if item.get("type") == "agent_message" and item.get("text"):
                content_parts.append(str(item["text"]))
        elif payload.get("type") == "turn.completed":
            raw_usage = payload.get("usage", {})
            usage = {
                "prompt_tokens": int(raw_usage.get("input_tokens", 0)),
                "completion_tokens": int(raw_usage.get("output_tokens", 0)),
                "total_tokens": int(raw_usage.get("input_tokens", 0))
                + int(raw_usage.get("output_tokens", 0)),
            }

    content = "\n".join(part for part in content_parts if part).strip()
    if not usage:
        usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    if not content:
        raise RuntimeError("Codex CLI did not emit a final agent message.")
    return content, usage


def _codex_command(model: str, prompt: str) -> list[str]:
    """Build the `codex exec` subprocess command."""
    cmd = [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--model",
        model,
        "--ephemeral",
    ]

    cd = os.getenv("CODEX_GATEWAY_CD", "").strip()
    if cd:
        cmd.extend(["--cd", cd])

    extra_args = os.getenv("CODEX_GATEWAY_ARGS", "").strip()
    if extra_args:
        cmd.extend(shlex.split(extra_args))

    cmd.append(prompt)
    return cmd


def _parse_runtime_options(argv: list[str]) -> argparse.Namespace:
    """Parse optional runtime flags for the standalone gateway."""
    parser = argparse.ArgumentParser(prog="codex-gateway")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--model")
    parser.add_argument("--api-key")
    return parser.parse_args(argv)


async def _call_codex(
    system_prompt: str,
    user_prompt: str,
    model: str,
) -> dict[str, Any]:
    """Call `codex exec` and return an OpenAI-like result payload."""
    prompt = _build_codex_prompt(system_prompt, user_prompt)
    cmd = _codex_command(model, prompt)
    logger.debug("Launching Codex CLI gateway command: %s", cmd[:8])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(),
        timeout=_get_timeout_seconds(),
    )

    stdout_text = stdout.decode(errors="replace")
    stderr_text = stderr.decode(errors="replace")
    if proc.returncode != 0:
        err_excerpt = (stderr_text or stdout_text).strip()[-1200:]
        raise RuntimeError(f"codex exec exited {proc.returncode}: {err_excerpt}")

    result, usage = _extract_codex_response(stdout_text)
    if stderr_text.strip():
        logger.debug("Codex CLI stderr: %s", stderr_text.strip()[:500])

    return {
        "result": result,
        "usage": usage,
    }


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "platform": "codex-gateway"})


@app.get("/v1/models")
async def list_models(request: Request) -> JSONResponse:
    _check_auth(request)
    model = _get_default_model()
    return JSONResponse(
        {
            "object": "list",
            "data": [
                {
                    "id": model,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "openai",
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

    model = _resolve_model(str(body.get("model") or ""))
    system_prompt, user_prompt = _messages_to_prompt(messages)
    if not user_prompt:
        raise HTTPException(400, "No user message found")

    start = time.time()
    try:
        codex_result = await _call_codex(system_prompt, user_prompt, model)
    except (RuntimeError, asyncio.TimeoutError) as exc:
        raise HTTPException(502, f"Codex backend error: {exc}")

    elapsed_ms = int((time.time() - start) * 1000)
    content = codex_result.get("result", "")
    usage = codex_result.get(
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
            "_codex_meta": {
                "duration_ms": elapsed_ms,
            },
        }
    )


def main() -> None:
    options = _parse_runtime_options(sys.argv[1:])

    if options.host:
        os.environ["CODEX_GATEWAY_HOST"] = options.host
    if options.port is not None:
        os.environ["CODEX_GATEWAY_PORT"] = str(options.port)
    if options.model:
        os.environ["CODEX_GATEWAY_MODEL"] = options.model
    if options.api_key:
        os.environ["CODEX_GATEWAY_KEY"] = options.api_key

    host = os.getenv("CODEX_GATEWAY_HOST", DEFAULT_HOST)
    port = int(os.getenv("CODEX_GATEWAY_PORT", str(DEFAULT_PORT)))
    print(f"Codex CLI gateway starting on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
