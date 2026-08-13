from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_and_orca_missing_capabilities(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOORCA_JOBS_DIR", str(tmp_path))
    monkeypatch.delenv("GEOORCA_ORCA_PATH", raising=False)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        caps = client.get("/api/capabilities").json()
        assert caps["backend"]["available"]
        if not caps["orca"]["available"]:
            assert not caps["calculation"]["available"]


def test_malformed_job_id_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOORCA_JOBS_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/jobs/..%2F..%2Fsecret").status_code in {404, 422}

