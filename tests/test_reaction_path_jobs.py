from __future__ import annotations

import json
import time
from backend.app.chemistry.opi_adapter import OpiAdapter
from backend.app.config import LocalSettings
from backend.app.jobs.manager import JobManager
from backend.app.models import CalculationKind, JobCreate, JobState, ReactionPathSettings
from backend.app.reaction_path.importer import ParsedFrame
from backend.app.reaction_path.optimization import build_optimization_path, parse_scf_history


def test_reaction_request_uses_only_the_current_project(water_project):
    request = JobCreate.model_validate(
        {
            "mode": "orca",
            "calculationKind": "reaction-path",
            "project": water_project.model_dump(by_alias=True),
        }
    )
    assert request.calculation_kind == CalculationKind.REACTION_PATH
    assert request.project == water_project
    assert "product" not in request.model_dump(by_alias=True)


def test_scf_history_is_grouped_by_geometry_cycle_and_tolerates_utf8(tmp_path):
    output = tmp_path / "optimization.out"
    output.write_text(
        """GEOMETRY OPTIMIZATION CYCLE 1
Iteration Energy (Eh) Delta-E RMSDP MaxDP DIISErr
  1 -75.000000 0.0 1.0D-02 2.0D-02 3.0D-03
  2 -75.100000 -1.0D-01 1.0D-03 2.0D-03 3.0D-04
SCF CONVERGED AFTER 2 CYCLES — ok
GEOMETRY OPTIMIZATION CYCLE 2
Iteration Energy (Eh) Delta-E RMSDP MaxDP MaxGrad
  1 -75.200000 -1.0D-01 1.0D-04 2.0D-04 4.0D-05
*** FINAL ENERGY EVALUATION AT THE STATIONARY POINT ***
Iteration Energy (Eh) Delta-E RMSDP MaxDP MaxGrad
  1 -75.210000 -1.0D-02 1.0D-05 2.0D-05 4.0D-06
""",
        encoding="utf-8",
    )
    cycles = parse_scf_history(output)
    assert len(cycles) == 3
    assert cycles[0].converged is True
    assert cycles[0].iterations[-1].energy_hartree == -75.1
    assert cycles[1].iterations[0].diis_error is None
    assert cycles[1].iterations[0].max_gradient == 4e-5
    assert cycles[2].iterations[0].energy_hartree == -75.21


def test_schema_two_manifest_accepts_one_actual_geometry(tmp_path, water_project):
    trajectory = tmp_path / "optimization_trj.xyz"
    trajectory.write_text("trajectory", encoding="utf-8")
    frame = ParsedFrame(
        [atom.element for atom in water_project.atoms],
        [tuple(atom.position) for atom in water_project.atoms],
        -76.0,
    )
    result = build_optimization_path(
        tmp_path,
        water_project,
        [frame],
        [],
        [[]],
        ["step-000.gbw"],
        [True],
    )
    assert result.schema_version == 2
    assert result.path_type == "geometry-optimization"
    assert result.source_type == "orca-optimization"
    assert result.initial_guess == "PAtom"
    assert result.images[0].geometry_converged is True


def test_path_single_points_use_patom_then_previous_gbw(tmp_path, water_project):
    adapter = OpiAdapter()
    positions = [tuple(atom.position) for atom in water_project.atoms]
    first = adapter.build_path_single_point(
        water_project,
        positions,
        tmp_path,
        basename="step-000",
        previous_gbw=None,
    )
    first.write_input()
    previous = tmp_path / "step-000.gbw"
    previous.write_bytes(b"gbw")
    second = adapter.build_path_single_point(
        water_project,
        positions,
        tmp_path,
        basename="step-001",
        previous_gbw=previous,
    )
    second.write_input()
    first_text = (tmp_path / "step-000.inp").read_text(encoding="utf-8").lower()
    second_text = (tmp_path / "step-001.inp").read_text(encoding="utf-8").lower()
    assert "patom" in first_text
    assert "moread" in second_text
    assert "%moinp" in second_text and "step-000.gbw" in second_text


def test_legacy_neb_builder_remains_a_separate_adapter(tmp_path, water_project):
    reactant = tmp_path / "reactant.xyz"
    product = tmp_path / "product.xyz"
    xyz = "3\nwater\nO 0 0 0\nH .9 0 0\nH -.2 1.2 0\n"
    reactant.write_text(xyz, encoding="utf-8")
    product.write_text(xyz, encoding="utf-8")
    calculator = OpiAdapter().build_neb_calculator(
        reactant,
        product,
        water_project,
        ReactionPathSettings(imageCount=8),
        tmp_path,
    )
    calculator.write_input()
    text = (tmp_path / "reaction.inp").read_text(encoding="utf-8").lower()
    assert "neb" in text
    assert "nimages 8" in text


def test_manager_dispatches_optimization_path_without_product(
    monkeypatch, tmp_path, water_project
):
    called: list[str] = []

    def fake_run(self, project, workdir, **kwargs):
        called.append(project.name)
        (workdir / "reaction-path.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 2,
                    "pathType": "geometry-optimization",
                    "sourceType": "orca-optimization",
                    "atomCount": len(project.atoms),
                    "elements": [atom.element for atom in project.atoms],
                    "charge": project.total_charge,
                    "multiplicity": project.multiplicity,
                    "images": [],
                    "hasPhysicalTime": False,
                    "isPhysicalTimeTrajectory": False,
                    "initialGuess": "PAtom",
                    "energyUnit": "hartree",
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(OpiAdapter, "run_optimization_path", fake_run)
    manager = JobManager(
        LocalSettings(jobs_dir=str(tmp_path / "jobs"), orca_path="orca")
    )
    record = manager.create(
        water_project, "orca", calculation_kind=CalculationKind.REACTION_PATH
    )
    for _ in range(100):
        record = manager.get(record.id)
        if record.state not in {JobState.QUEUED, JobState.RUNNING}:
            break
        time.sleep(0.01)
    assert record.state == JobState.SUCCEEDED
    assert called == [water_project.name]
    folder = manager._job_dir(record.id)
    assert (folder / "optimization-input.xyz").is_file()
    assert not (folder / "product-project.json").exists()
