"""Tests for risk-model training artifact generation."""
import json

from scoring import train_risk_model


def test_train_risk_model_exports_expected_artifact(monkeypatch, tmp_path):
    artifact = tmp_path / "risk_model.json"
    monkeypatch.setattr(train_risk_model, "ARTIFACT", artifact)

    train_risk_model.main()

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["training_algorithm"] == "agglomerative"
    assert payload["inference_strategy"] == "nearest_centroid_proxy"
    assert payload["features"] == train_risk_model.FEATURES
    assert payload["n_clusters"] == 3
    assert sum(payload["cluster_sizes"].values()) == 150
    assert set(payload["cluster_to_bucket"].values()) == {
        "LEGITIMO",
        "AMBIGUO",
        "FRAUDE",
    }
