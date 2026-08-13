from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from backend.app.models import Atom, JobMode, Orbital, PlotSampleRequest
from backend.app.plots.geometry import atom_line, atom_plane
from backend.app.plots.interpolation import trilinear_sample
from backend.app.plots.service import PlotSamplingService
from backend.app.surfaces.cube import CubeData


def linear_cube() -> CubeData:
    shape = (5, 5, 5)
    i, j, k = np.meshgrid(*(np.arange(n) for n in shape), indexing="ij")
    return CubeData(np.zeros(3), np.eye(3), shape, i + 2 * j + 3 * k)


def test_trilinear_interpolation_matches_linear_field_and_marks_outside_invalid():
    values, valid = trilinear_sample(
        linear_cube(), np.asarray([[1.5, 2.0, 0.5], [-1.0, 0.0, 0.0]])
    )
    assert values[0] == pytest.approx(7.0)
    assert valid.tolist() == [True, False]
    assert np.isnan(values[1])


def test_atom_cut_coordinate_systems_have_requested_orientation():
    origin, direction = atom_line(np.array([1.0, 0, 0]), np.array([3.0, 0, 0]))
    assert np.allclose(origin, [1, 0, 0])
    assert np.allclose(direction, [1, 0, 0])
    origin, u, v = atom_plane(
        np.array([1.0, 1, 0]), np.array([2.0, 1, 0]), np.array([1.0, 2, 0])
    )
    assert np.dot(np.array([1.0, 2, 0]) - origin, v) > 0
    assert np.allclose(u, [1, 0, 0])


class FakeJobs:
    def __init__(self, tmp_path, result):
        self.tmp_path = tmp_path
        self._result = result

    def get(self, _job_id):
        return SimpleNamespace(mode=JobMode.ORCA)

    def result(self, _job_id):
        return self._result

    def _job_dir(self, _job_id):
        return self.tmp_path


class FakeFields:
    def load(self, _job_dir, _field, *, resolution):
        assert resolution == 40
        return linear_cube(), True


def test_line_and_plane_sampling_return_separate_field_payloads(tmp_path):
    atom_id = uuid4()
    result = SimpleNamespace(
        demo=False,
        optimized_atoms=[Atom(id=atom_id, element="H", position=(1, 1, 1))],
        orbitals=[Orbital(
            internal_id="restricted:0", orca_index=0, display_number=1,
            energy_hartree=-0.5, occupancy=2, spin="restricted",
        )],
    )
    service = PlotSamplingService(FakeJobs(tmp_path, result), FakeFields())
    line = service.sample(uuid4(), PlotSampleRequest.model_validate({
        "field": {"field": "mo", "orbital_internal_id": "restricted:0", "orbital_index": 0},
        "cut": {"kind": "axis_line", "axis": "x", "offsets": [1, 1]},
        "bounds": {"automatic": False, "s": [0, 3]},
        "line_samples": 32,
    }))
    plane = service.sample(uuid4(), PlotSampleRequest.model_validate({
        "field": {"field": "total_density"},
        "cut": {"kind": "axis_plane", "plane": "xy", "offset": 1},
        "bounds": {"automatic": False, "u": [0, 3], "v": [0, 3]},
        "plane_samples_u": 16, "plane_samples_v": 16,
    }))
    assert line["kind"] == "line" and line["field"]["field"] == "mo"
    assert plane["kind"] == "plane" and plane["field"]["field"] == "total_density"
    assert len(plane["values"]) == 16
