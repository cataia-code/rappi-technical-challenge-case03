"""Smoke tests for the FastAPI boundary."""
from fastapi.testclient import TestClient

from apps.api.main import app


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_review_dataset_case_without_llm():
    response = client.post("/cases/COMP-0001/decisions")

    assert response.status_code == 200
    body = response.json()
    assert body["caso_id"] == "COMP-0001"
    assert body["recomendacion"] == "APROBAR"
    assert body["risk_bucket"] == "LEGITIMO"


def test_unknown_dataset_case_returns_404():
    response = client.post("/cases/UNKNOWN/decisions")

    assert response.status_code == 404
