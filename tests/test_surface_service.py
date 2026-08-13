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


def test_mo_cube_generation_is_lazy_cached_and_spin_specific(monkeypatch, tmp_path):
    (tmp_path / "electronic.gbw").write_bytes(b"gbw")
    plot_calls: list[tuple[int, int]] = []

    class FakeOutput:
        def __init__(self, _basename, *, working_dir, **_kwargs):
            self.working_dir = working_dir
            self.gbw_json_files = []

        def collect_gbw_json_files(self):
            self.gbw_json_files = [self.working_dir / "electronic.gbw.json"]

        def plot_mo(self, index, *, operator, **_kwargs):
            plot_calls.append((index, operator))
            return SimpleNamespace(cube=f"MO {index}, operator {operator}")

    monkeypatch.setattr("opi.output.core.Output", FakeOutput)

    alpha_request = SurfaceRequest(
        field="mo", orbital_index=17, spin="alpha", isovalue=0.03
    )
    beta_request = SurfaceRequest(
        field="mo", orbital_index=17, spin="beta", isovalue=0.03
    )
    restricted_request = SurfaceRequest(
        field="mo", orbital_index=17, spin="restricted", isovalue=0.03
    )

    alpha_path = SurfaceService._find_or_generate_cube(tmp_path, alpha_request)
    assert SurfaceService._find_or_generate_cube(tmp_path, alpha_request) == alpha_path
    beta_path = SurfaceService._find_or_generate_cube(tmp_path, beta_request)
    restricted_path = SurfaceService._find_or_generate_cube(tmp_path, restricted_request)

    assert alpha_path.name == "electronic.mo.alpha.17.cube"
    assert beta_path.name == "electronic.mo.beta.17.cube"
    assert restricted_path.name == "electronic.mo.restricted.17.cube"
    assert len({alpha_path, beta_path, restricted_path}) == 3
    assert plot_calls == [(17, 0), (17, 1), (17, 0)]
    assert sorted(path.name for path in tmp_path.glob("*.cube")) == [
        "electronic.mo.alpha.17.cube",
        "electronic.mo.beta.17.cube",
        "electronic.mo.restricted.17.cube",
    ]
