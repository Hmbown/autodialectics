# CLIProxyAPI Go SDK Extension

This document describes the planned integration path for richer CLIProxyAPI functionality via a Go SDK sidecar.

## Current State

Autodialectics currently communicates with CLIProxyAPI through its OpenAI-compatible `/v1/chat/completions` HTTP endpoint. The Python runtime treats CLIProxyAPI as a generic LLM proxy and has no visibility into routing decisions, model registry, or configuration changes.

## Planned SDK Integration

### 1. Model Registry

The Go SDK will expose a model registry API that allows Autodialectics to:
- Query available models and their capabilities (context window, cost tier, latency)
- Set model preferences per pipeline role (planner, critic, synthesist, executor, verifier)
- Receive model availability events (new models added, models removed or degraded)

```
GET /api/v1/models          -> list available models
POST /api/v1/models/prefer  -> set role-to-model mapping
```

### 2. Richer Routing

Beyond simple role-based routing, the SDK will support:
- **A/B routing**: Send a fraction of requests to a challenger model for comparison
- **Cost-aware routing**: Route to cheaper models for low-stakes pipeline stages
- **Latency-aware routing**: Prefer faster models when pipeline time budget is constrained
- **Fallback chains**: Define ordered fallback models when the primary is unavailable

```
POST /api/v1/route/config   -> set routing strategy
GET  /api/v1/route/stats    -> get routing statistics
```

### 3. Request/Response Hooks

The SDK will support webhook-style hooks for observability:
- **Pre-request hooks**: Inspect and modify prompts before they reach the model (e.g., inject additional context, redact sensitive data)
- **Post-response hooks**: Inspect model responses before returning to Autodialectics (e.g., log token usage, detect anomalies)

```
POST /api/v1/hooks/register  -> register a hook
POST /api/v1/hooks/event     -> receive hook events
```

### 4. Hot-Reload Watcher Events

Configuration changes in CLIProxyAPI should be communicated to the Python runtime in real-time:
- Model registry changes
- API key rotation
- Routing strategy updates
- Rate limit changes

The SDK will use a lightweight event stream (SSE or WebSocket):

```
GET /api/v1/events/stream  -> SSE event stream
```

Events:
```json
{"type": "model_added", "model": "gpt-4.1", "capabilities": {"context_window": 128000}}
{"type": "config_changed", "key": "default-model", "old": "gpt-4.1-mini", "new": "gpt-4.1"}
{"type": "rate_limit", "model": "gpt-4.1", "rpm": 500, "remaining": 120}
```

## Integration Architecture

```
┌─────────────────────┐     HTTP/REST     ┌──────────────────┐
│  Autodialectics     │◄──────────────────►│  CLIProxyAPI     │
│  (Python Runtime)   │                    │  (Go Sidecar)    │
│                     │   /v1/chat/        │                  │
│  - Pipeline         │   completions      │  - Model Router  │
│  - Slop Scoring     │                    │  - Model Registry│
│  - Evolution        │   /api/v1/         │  - Hooks         │
│                     │   models, hooks,   │  - Events        │
│                     │   events           │  - Metrics       │
└─────────────────────┘                    └──────────────────┘
```

## Implementation Roadmap

1. **Phase 1**: Add model registry query support to the Python `ModelClient`
2. **Phase 2**: Implement role-based model preferences using registry queries
3. **Phase 3**: Add pre/post-request hooks for observability
4. **Phase 4**: SSE event stream for real-time configuration updates
5. **Phase 5**: A/B routing integration with the evolution pipeline

## Compatibility

The SDK integration is fully backward-compatible. If the CLIProxyAPI sidecar is not running or doesn't expose the extended APIs, Autodialectics falls back to basic OpenAI-compatible completion and offline mode.
