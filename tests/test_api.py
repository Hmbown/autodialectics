"""Tests for the FastAPI endpoints."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(runtime):
    """Create a test client with the runtime injected."""
    from autodialectics.api.app import app, get_runtime, reset_runtime

    # Reset and inject our test runtime
    reset_runtime()

    def override_runtime():
        return runtime

    app.dependency_overrides[get_runtime] = override_runtime

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    reset_runtime()


def test_health_endpoint(client: TestClient) -> None:
    """GET /health should return {'status': 'ok'}."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_compile_endpoint(client: TestClient) -> None:
    """POST /tasks/compile with a TaskSubmission should return a TaskContract."""
    payload = {
        "title": "API compile test",
        "description": "Testing the compile endpoint via API.",
    }
    resp = client.post("/tasks/compile", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "API compile test"
    assert data["source_hash"]
    assert data["domain"]
    assert "evaluation_rubric" in data
    assert "forbidden_shortcuts" in data


def test_runs_endpoint(client: TestClient) -> None:
    """POST /runs creates a run, GET /runs/{id} returns it."""
    # Create a run
    payload = {
        "submission": {
            "title": "API run test",
            "description": "Testing the runs endpoint via API.",
        }
    }
    resp = client.post("/runs", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    run_id = data["run_id"]
    assert run_id

    # Retrieve the run
    resp = client.get(f"/runs/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "manifest" in data
    assert data["manifest"]["run_id"] == run_id
