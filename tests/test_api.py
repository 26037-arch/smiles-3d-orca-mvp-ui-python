from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.models import OrbitalComposition


def test_health_and_orca_missing_capabilities(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOORCA_JOBS_DIR", str(tmp_path))
    monkeypatch.delenv("GEOORCA_ORCA_PATH", raising=False)
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["status"] == "ok"
        assert health["surface_pipeline"] == "cube-parser-v4"
        caps = client.get("/api/capabilities").json()
        assert caps["backend"]["available"]
        if not caps["orca"]["available"]:
            assert not caps["calculation"]["available"]


def test_malformed_job_id_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOORCA_JOBS_DIR", str(tmp_path))
    with TestClient(app) as client:
        assert client.get("/api/jobs/..%2F..%2Fsecret").status_code in {404, 422}


def test_orbital_composition_route_preserves_five_item_paging(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOORCA_JOBS_DIR", str(tmp_path))
    job_id = "00000000-0000-0000-0000-000000000001"
    captured = []

    class FakeAO:
        def composition(self, received_job_id, spin, orca_index, *, offset, limit):
            captured.append((str(received_job_id), spin, orca_index, offset, limit))
            return OrbitalComposition(
                orbital_internal_id="alpha:4",
                energy_hartree=-0.428,
                items=[],
                groups=[],
                offset=offset,
                limit=limit,
                total=12,
                has_more=offset + limit < 12,
            )

    with TestClient(app) as client:
        client.app.state.ao = FakeAO()
        response = client.get(
            f"/api/jobs/{job_id}/orbitals/alpha/4/composition?offset=5&limit=5"
        )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["offset"] == 5
    assert response.json()["limit"] == 5
    assert captured == [(job_id, "alpha", 4, 5, 5)]
