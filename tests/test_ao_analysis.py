from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from backend.app.ao.analysis import (
    contribution_models,
    loewdin_contributions,
    parse_orca_gbw_json,
)
from backend.app.ao.service import AOAnalysisService, _identify_ao_cube
from backend.app.chemistry.opi_adapter import ChemistryError
from backend.app.config import LocalSettings
from backend.app.models import (
    BasisSurfaceRequest,
    CalculationResult,
    JobMode,
    Orbital,
)


FIXTURE = Path(__file__).parent / "fixtures" / "orca61_ao.json"


def fixture_document():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_identity_overlap_is_coefficient_squared_and_phase_normalized():
    coefficients, weights = loewdin_contributions(np.eye(3), np.array([-0.8, 0.0, -0.6]))

    assert coefficients.tolist() == pytest.approx([0.8, 0.0, 0.6])
    assert weights.tolist() == pytest.approx([0.64, 0.0, 0.36])
    assert weights.sum() == pytest.approx(1.0)


def test_nonorthogonal_positive_overlap_is_normalized():
    overlap = np.array([[1.0, 0.2], [0.2, 1.0]])
    raw = np.array([0.8, 0.5])
    normalized = raw / np.sqrt(raw @ overlap @ raw)

    _, weights = loewdin_contributions(overlap, normalized)

    assert weights.sum() == pytest.approx(1.0)
    assert np.all(weights >= 0.0)


def test_negative_eigenvalue_tolerance_and_significant_failure():
    _, weights = loewdin_contributions(
        np.diag([1.0, -1.0e-12]), np.array([1.0, 0.0])
    )
    assert weights.tolist() == pytest.approx([1.0, 0.0])

    with pytest.raises(ChemistryError, match="negative eigenvalue") as caught:
        loewdin_contributions(np.diag([1.0, -1.0e-3]), np.array([1.0, 0.0]))
    assert caught.value.code == "AO_OVERLAP_NOT_POSITIVE_SEMIDEFINITE"


def test_fixture_parser_uses_orca_basis_order_and_groups_contributions():
    parsed = parse_orca_gbw_json(fixture_document(), "restricted", 0)
    items, groups = contribution_models(parsed)

    assert [item.basis_index for item in items] == [0, 1]
    assert [item.coefficient for item in items] == pytest.approx([0.8, 0.6])
    assert sum(item.percentage for item in items) == pytest.approx(100.0)
    assert [(group.atom_label, group.ao_label) for group in groups] == [
        ("H1", "s similar"),
        ("H2", "s similar"),
    ]


def test_uhf_alpha_beta_channel_mapping_is_half_split():
    document = fixture_document()
    molecule = document["Molecule"]
    molecule["HFTyp"] = "UHF"
    alpha = molecule["MolecularOrbitals"]["MOs"]
    beta = [
        {**alpha[0], "OrbitalEnergy": -0.45},
        {**alpha[1], "OrbitalEnergy": 0.30},
    ]
    molecule["MolecularOrbitals"]["MOs"] = [*alpha, *beta]

    assert parse_orca_gbw_json(document, "alpha", 0).energy_hartree == pytest.approx(-0.5)
    assert parse_orca_gbw_json(document, "beta", 0).energy_hartree == pytest.approx(-0.45)
    with pytest.raises(ChemistryError) as caught:
        parse_orca_gbw_json(document, "restricted", 0)
    assert caught.value.code == "AO_SPIN_INDEX_MISMATCH"


def test_grouping_sums_repeated_atom_angular_components():
    document = fixture_document()
    molecule = document["Molecule"]
    molecule["Atoms"] = [
        {
            **molecule["Atoms"][0],
            "Basis": [
                {"Coefficients": [1.0], "Exponents": [2.0], "Shell": "s"},
                {"Coefficients": [1.0], "Exponents": [1.0], "Shell": "s"},
            ],
        }
    ]
    molecule["S-Matrix"] = [[1.0, 0.0], [0.0, 1.0]]
    molecule["MolecularOrbitals"]["MOs"][0]["MOCoefficients"] = [0.8, 0.6]
    parsed = parse_orca_gbw_json(document, "restricted", 0)
    _, groups = contribution_models(parsed)

    assert len(groups) == 1
    assert groups[0].count == 2
    assert groups[0].basis_indices == [0, 1]
    assert groups[0].percentage == pytest.approx(100.0)


class FakeJobs:
    def __init__(self, job_dir, *, mode=JobMode.ORCA):
        self.job_dir = job_dir
        self.mode = mode
        self.job_id = uuid4()
        self.calculation = CalculationResult(
            job_id=self.job_id,
            optimized_atoms=[],
            total_energy_hartree=-1.0,
            normal_termination=True,
            scf_converged=True,
            geometry_converged=True,
            orbitals=[
                Orbital(
                    internal_id="restricted:0",
                    orca_index=0,
                    display_number=1,
                    energy_hartree=-0.5,
                    occupancy=2.0,
                )
            ],
            demo=mode == JobMode.DEMO,
        )

    def get(self, _job_id):
        return SimpleNamespace(mode=self.mode)

    def result(self, _job_id):
        return self.calculation

    def _job_dir(self, _job_id):
        return self.job_dir


def make_service(tmp_path, extractor, *, mode=JobMode.ORCA, cube_generator=None):
    (tmp_path / "electronic.gbw").write_bytes(b"gbw-v1")
    jobs = FakeJobs(tmp_path, mode=mode)
    service = AOAnalysisService(
        jobs,
        LocalSettings(jobs_dir=str(tmp_path)),
        extractor=extractor,
        cube_generator=cube_generator,
    )
    return service, jobs


def test_composition_pagination_cache_hit_invalidation_and_duplicate_prevention(tmp_path):
    calls = []

    def extract(_job_dir, _gbw):
        calls.append(1)
        return fixture_document()

    service, jobs = make_service(tmp_path, extract)
    first = service.composition(jobs.job_id, "restricted", 0, offset=0, limit=1)
    second = service.composition(jobs.job_id, "restricted", 0, offset=1, limit=1)
    assert [item.basis_index for item in first.items] == [0]
    assert [item.basis_index for item in second.items] == [1]
    assert first.total == 2 and first.has_more
    assert second.total == 2 and not second.has_more and second.cache_hit
    assert len(calls) == 1

    (tmp_path / "electronic.gbw").write_bytes(b"gbw-v2")
    service.composition(jobs.job_id, "restricted", 0, offset=0, limit=1)
    assert len(calls) == 2

    (tmp_path / "electronic.gbw").write_bytes(b"gbw-v3")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(
            pool.map(
                lambda _: service.composition(
                    jobs.job_id, "restricted", 0, offset=0, limit=1
                ),
                range(4),
            )
        )
    assert len(calls) == 3


def test_rejects_demo_and_wrong_mo_or_basis_index(tmp_path):
    service, jobs = make_service(tmp_path, lambda *_: fixture_document(), mode=JobMode.DEMO)
    with pytest.raises(ChemistryError) as caught:
        service.composition(jobs.job_id, "restricted", 0, offset=0, limit=5)
    assert caught.value.code == "AO_DEMO_UNAVAILABLE"

    service, jobs = make_service(tmp_path, lambda *_: fixture_document())
    with pytest.raises(ChemistryError) as caught:
        service.composition(jobs.job_id, "restricted", 99, offset=0, limit=5)
    assert caught.value.code == "AO_MO_INDEX_MISMATCH"
    with pytest.raises(ChemistryError) as caught:
        service.create_surface(
            jobs.job_id,
            "restricted",
            0,
            99,
            BasisSurfaceRequest(),
        )
    assert caught.value.code == "AO_BASIS_INDEX_MISMATCH"


def test_ao_surface_scales_cube_by_phase_normalized_mo_coefficient(
    monkeypatch, tmp_path
):
    def cube_generator(_job_dir, _gbw, _basis_index, output):
        output.write_text(
            "component\ncube\n1 0 0 0\n2 1 0 0\n2 0 1 0\n2 0 0 1\n"
            "1 0 0 0 0\n-0.10 0.10 -0.10 0.10 -0.10 0.10 -0.10 0.10\n",
            encoding="ascii",
        )

    generated = []
    mesh_outputs = []

    def contour(cube, level, output):
        generated.append((cube.values.copy(), level))
        mesh_outputs.append(output)
        output.write_bytes(b"ply")

    monkeypatch.setattr("backend.app.ao.service.contour_to_ply", contour)
    service, jobs = make_service(
        tmp_path, lambda *_: fixture_document(), cube_generator=cube_generator
    )
    record = service.create_surface(
        jobs.job_id,
        "restricted",
        0,
        0,
        BasisSurfaceRequest(isovalue=0.03),
    )

    assert record.phases == ["positive", "negative"]
    assert [level for _, level in generated] == [0.03, -0.03]
    assert generated[0][0].min() == pytest.approx(-0.08)
    assert generated[0][0].max() == pytest.approx(0.08)
    assert all(path.suffix == ".ply" for path in mesh_outputs)
    assert all(path.name.endswith(".tmp.ply") for path in mesh_outputs)


def test_different_basis_surfaces_serialize_orca_plot_per_gbw(monkeypatch, tmp_path):
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0
    generated_basis = []

    def cube_generator(_job_dir, _gbw, basis_index, output):
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
            generated_basis.append(basis_index)
        try:
            time.sleep(0.05)
            output.write_text(
                "component\ncube\n1 0 0 0\n2 1 0 0\n2 0 1 0\n2 0 0 1\n"
                "1 0 0 0 0\n-0.10 0.10 -0.10 0.10 -0.10 0.10 -0.10 0.10\n",
                encoding="ascii",
            )
        finally:
            with state_lock:
                active -= 1

    def contour(_cube, _level, output):
        output.write_bytes(b"ply")

    monkeypatch.setattr("backend.app.ao.service.contour_to_ply", contour)
    service, jobs = make_service(
        tmp_path, lambda *_: fixture_document(), cube_generator=cube_generator
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(
            pool.map(
                lambda basis_index: service.create_surface(
                    jobs.job_id,
                    "restricted",
                    0,
                    basis_index,
                    BasisSurfaceRequest(isovalue=0.03),
                ),
                [0, 1],
            )
        )

    assert len(records) == 2
    assert sorted(generated_basis) == [0, 1]
    assert maximum_active == 1


def test_ao_cube_identification_prefers_exact_then_reported_filename(tmp_path):
    gbw = tmp_path / "electronic.gbw"
    exact = tmp_path / "electronic.ao7.cube"
    unrelated = tmp_path / "other.cube"

    assert _identify_ao_cube(tmp_path, gbw, 7, [unrelated, exact], "") == exact
    assert _identify_ao_cube(
        tmp_path,
        gbw,
        8,
        [unrelated, exact],
        "Output file ... other.cube",
    ) == unrelated


def test_empty_ao_isosurface_and_cube_tool_failures_are_structured(tmp_path):
    def small_cube(_job_dir, _gbw, _basis_index, output):
        output.write_text(
            "component\ncube\n1 0 0 0\n2 1 0 0\n2 0 1 0\n2 0 0 1\n"
            "1 0 0 0 0\n-0.01 0.01 -0.01 0.01 -0.01 0.01 -0.01 0.01\n",
            encoding="ascii",
        )

    service, jobs = make_service(
        tmp_path, lambda *_: fixture_document(), cube_generator=small_cube
    )
    with pytest.raises(ChemistryError) as caught:
        service.create_surface(
            jobs.job_id, "restricted", 0, 0, BasisSurfaceRequest(isovalue=0.03)
        )
    assert caught.value.code == "AO_EMPTY_ISOSURFACE"

    def fail_cube(*_args):
        raise ChemistryError("AO_CUBE_GENERATION_FAILED", "mock tool failure")

    (tmp_path / "ao-cubes").joinpath(
        next((tmp_path / "ao-cubes").iterdir()).name
    ).unlink()
    service.cube_generator = fail_cube
    with pytest.raises(ChemistryError) as caught:
        service.create_surface(
            jobs.job_id, "restricted", 0, 0, BasisSurfaceRequest(isovalue=0.003)
        )
    assert caught.value.code == "AO_CUBE_GENERATION_FAILED"
