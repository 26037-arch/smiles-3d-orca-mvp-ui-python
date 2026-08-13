from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from backend.app.models import JobMode, SurfaceRequest
from backend.app.surfaces.cube import CubeData
from backend.app.surfaces.service import SurfaceService


class FakeJobs:
    def __init__(self, job_dir):
        self.job_dir = job_dir

    def get(self, _job_id):
        return SimpleNamespace(mode=JobMode.ORCA)

    def result(self, _job_id):
        return object()

    def _job_dir(self, _job_id):
        return self.job_dir


def make_cube(values: np.ndarray) -> CubeData:
    return CubeData(
        origin=np.zeros(3),
        axes=np.eye(3),
        shape=values.shape,
        values=values,
    )


def create_surface(monkeypatch, tmp_path, values: np.ndarray):
    cube_path = tmp_path / "orbital.cube"
    cube_path.write_text("cube", encoding="ascii")
    generated_levels: list[float] = []

    monkeypatch.setattr(
        SurfaceService,
        "_find_or_generate_cube",
        staticmethod(lambda _job_dir, _request: cube_path),
    )
    monkeypatch.setattr(
        "backend.app.surfaces.service.read_cube",
        lambda _path: make_cube(values),
    )

    def write_mesh(_cube, level, output):
        generated_levels.append(level)
        output.write_bytes(b"ply")

    monkeypatch.setattr("backend.app.surfaces.service.contour_to_ply", write_mesh)
    record = SurfaceService(FakeJobs(tmp_path)).create(
        uuid4(),
        SurfaceRequest(field="mo", orbital_index=0, isovalue=0.03),
    )
    return record, generated_levels


def test_surface_service_keeps_positive_phase_when_negative_is_absent(monkeypatch, tmp_path):
    record, levels = create_surface(
        monkeypatch,
        tmp_path,
        np.array([[[0.0, 0.01], [0.02, 0.04]]]),
    )

    assert record.phases == ["positive"]
    assert set(record.mesh_urls) == {"positive"}
    assert levels == [0.03]


def test_surface_service_keeps_negative_phase_when_positive_is_absent(monkeypatch, tmp_path):
    record, levels = create_surface(
        monkeypatch,
        tmp_path,
        np.array([[[-0.04, -0.02], [-0.01, 0.0]]]),
    )

    assert record.phases == ["negative"]
    assert set(record.mesh_urls) == {"negative"}
    assert levels == [-0.03]


def test_surface_service_keeps_both_available_phases(monkeypatch, tmp_path):
    record, levels = create_surface(
        monkeypatch,
        tmp_path,
        np.array([[[-0.04, -0.01], [0.01, 0.04]]]),
    )

    assert record.phases == ["positive", "negative"]
    assert set(record.mesh_urls) == {"positive", "negative"}
    assert levels == [0.03, -0.03]


def test_surface_service_rejects_only_when_both_phases_are_absent(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="표면이 비어 있습니다"):
        create_surface(
            monkeypatch,
            tmp_path,
            np.array([[[-0.02, -0.01], [0.01, 0.02]]]),
        )
