from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.models import (
    CalculationKind,
    JobMode,
    JobRecord,
    JobState,
    OrbitalComposition,
)


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


def test_job_events_serialize_calculation_kind_with_frontend_alias(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOORCA_JOBS_DIR", str(tmp_path))
    job_id = UUID("00000000-0000-0000-0000-000000000003")

    class FakeJobs:
        def get(self, received_job_id):
            assert received_job_id == job_id
            return JobRecord(
                id=job_id,
                state=JobState.SUCCEEDED,
                mode=JobMode.ORCA,
                calculationKind=CalculationKind.REACTION_PATH,
                created_at="2026-08-14T00:00:00+00:00",
                updated_at="2026-08-14T00:00:01+00:00",
                progress=1,
                message="완료",
            )

        def log_text(self, received_job_id):
            assert received_job_id == job_id
            return "최적화 경로 manifest 저장"

    with TestClient(app) as client:
        original_jobs = client.app.state.jobs
        try:
            client.app.state.jobs = FakeJobs()
            response = client.get(f"/api/jobs/{job_id}/events")
        finally:
            client.app.state.jobs = original_jobs

    assert response.status_code == 200
    assert '"calculationKind": "reaction-path"' in response.text
    assert '"calculation_kind"' not in response.text


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


def test_reaction_path_route_loads_versioned_manifest(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOORCA_JOBS_DIR", str(tmp_path))
    job_id = "00000000-0000-0000-0000-000000000002"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    shutil.copy(Path(__file__).parent / "fixtures" / "reaction-path.json", job_dir)
    with TestClient(app) as client:
        response = client.get(f"/api/jobs/{job_id}/reaction-path")
    assert response.status_code == 200
    payload = response.json()
    assert payload["path"]["schemaVersion"] == 1
    assert len(payload["displayFrames"]) == 17
    assert payload["displayFrames"][0]["isCalculated"] is True
    assert payload["displayFrames"][1]["isCalculated"] is False


def test_reaction_path_route_lazily_generates_manifest(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOORCA_JOBS_DIR", str(tmp_path))
    job_id = "00000000-0000-0000-0000-000000000003"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    (job_dir / "reaction_MEP_trj.xyz").write_text(
        "2\nEnergy = -5.0 Eh\nH 0 0 0\nH 1 0 0\n"
        "2\nEnergy = -4.9 Eh\nH 0.1 0 0\nH 1.1 0 0\n",
        encoding="utf-8",
    )
    with TestClient(app) as client:
        response = client.get(f"/api/jobs/{job_id}/reaction-path")
    assert response.status_code == 200
    assert response.json()["path"]["sourceType"] == "neb"
    assert (job_dir / "reaction-path.json").is_file()


def test_reaction_path_route_distinguishes_missing_and_invalid_source(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOORCA_JOBS_DIR", str(tmp_path))
    missing_id = "00000000-0000-0000-0000-000000000004"
    invalid_id = "00000000-0000-0000-0000-000000000005"
    (tmp_path / missing_id).mkdir()
    invalid_dir = tmp_path / invalid_id
    invalid_dir.mkdir()
    (invalid_dir / "reaction_IRC_Full_trj.xyz").write_text(
        "2\ncomment\nH 0 0 0\n", encoding="utf-8"
    )
    with TestClient(app) as client:
        missing = client.get(f"/api/jobs/{missing_id}/reaction-path")
        invalid = client.get(f"/api/jobs/{invalid_id}/reaction-path")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "REACTION_PATH_NOT_FOUND"
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "TRUNCATED_XYZ_FRAME"


def test_reaction_tracking_and_geometry_surface_routes_are_separate(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOORCA_JOBS_DIR", str(tmp_path))
    job_id = "00000000-0000-0000-0000-000000000006"
    calls: list[tuple] = []

    class FakeReactionPaths:
        def track_orbital(self, received_job_id, orbital_id, source_geometry_index):
            calls.append(("track", str(received_job_id), orbital_id, source_geometry_index))
            return {"trackingId": "a" * 32, "steps": [], "active": True}

        def create_geometry_surface(self, received_job_id, geometry_index, body):
            calls.append(("geometry", str(received_job_id), geometry_index, body.field))
            return {"mesh_urls": {"positive": "/mesh"}, "cache_hit": False}

        def tracking_frame_surface(
            self, received_job_id, tracking_id, frame_index, isovalue
        ):
            calls.append(
                ("frame", str(received_job_id), tracking_id, frame_index, isovalue)
            )
            return {"frameIndex": frame_index, "meshUrls": {}, "cacheHit": False}

    with TestClient(app) as client:
        original = client.app.state.reaction_paths
        client.app.state.reaction_paths = FakeReactionPaths()
        try:
            tracked = client.post(
                f"/api/jobs/{job_id}/reaction-path/orbitals/track",
                json={"orbital_id": "restricted:7", "source_geometry_index": 2},
            )
            geometry = client.post(
                f"/api/jobs/{job_id}/reaction-path/geometries/2/surfaces",
                json={"field": "mo", "orbital_index": 7},
            )
            frame = client.post(
                f"/api/jobs/{job_id}/reaction-path/tracking/{'a' * 32}/frames/11/surface",
                json={"isovalue": 0.04},
            )
        finally:
            client.app.state.reaction_paths = original

    assert tracked.status_code == geometry.status_code == frame.status_code == 200
    assert calls == [
        ("track", job_id, "restricted:7", 2),
        ("geometry", job_id, 2, "mo"),
        ("frame", job_id, "a" * 32, 11, 0.04),
    ]
