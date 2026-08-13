from __future__ import annotations

import json
import time
from threading import Event

import pytest
from fastapi.testclient import TestClient

from backend.app.chemistry.opi_adapter import ChemistryError, OpiAdapter
from backend.app.config import LocalSettings
from backend.app.jobs.manager import JobManager
from backend.app.main import app
from backend.app.models import (
    CalculationKind,
    JobCreate,
    JobMode,
    JobState,
    ReactionPathSettings,
)


def product_from(project, *, displacement: float = 0.35):
    atoms = list(project.atoms)
    atoms[-1] = atoms[-1].model_copy(
        update={"position": (atoms[-1].position[0], atoms[-1].position[1] + displacement, 0)}
    )
    return project.model_copy(update={"name": "Water product", "atoms": atoms})


def wait_terminal(manager: JobManager, job_id, timeout: float = 4):
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = manager.get(job_id)
        if record.state in {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}:
            return record
        time.sleep(0.02)
    raise AssertionError("reaction-path job did not finish")


def trajectory_text(reactant, product) -> str:
    def frame(project, energy):
        rows = [str(len(project.atoms)), f"Energy = {energy} Eh"]
        rows.extend(
            f"{atom.element} {atom.position[0]} {atom.position[1]} {atom.position[2]}"
            for atom in project.atoms
        )
        return "\n".join(rows)

    return frame(reactant, -76.0) + "\n" + frame(product, -75.9) + "\n"


def test_legacy_single_request_defaults_are_preserved(water_project):
    request = JobCreate.model_validate(
        {"mode": "demo", "project": water_project.model_dump(by_alias=True)}
    )
    assert request.calculation_kind == CalculationKind.SINGLE
    assert request.reaction_path_settings.image_count == 8


def test_job_request_does_not_mix_single_and_reaction_payloads(water_project):
    with pytest.raises(ValueError, match="reactant와 product"):
        JobCreate(
            mode="orca",
            calculationKind="reaction-path",
            project=water_project,
            reactant=water_project,
            product=product_from(water_project),
        )


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda product: product.model_copy(update={"atoms": product.atoms[:-1]}),
         "ENDPOINT_ATOM_COUNT_MISMATCH"),
        (
            lambda product: product.model_copy(
                update={
                    "atoms": [
                        product.atoms[0].model_copy(update={"element": "H"}),
                        product.atoms[1].model_copy(update={"element": "O"}),
                        product.atoms[2],
                    ]
                }
            ),
            "ENDPOINT_ELEMENT_ORDER_MISMATCH",
        ),
        (lambda product: product.model_copy(update={"total_charge": 1}),
         "ENDPOINT_CHARGE_MISMATCH"),
    ],
)
def test_endpoint_validation_has_stable_error_codes(tmp_path, water_project, mutation, code):
    manager = JobManager(LocalSettings(jobs_dir=str(tmp_path), orca_path="orca"))
    product = mutation(product_from(water_project))
    with pytest.raises(ChemistryError) as error:
        manager.create(
            water_project,
            JobMode.ORCA,
            calculation_kind=CalculationKind.REACTION_PATH,
            product=product,
        )
    assert error.value.code == code
    manager.executor.shutdown()


def test_api_rejects_missing_product_with_structured_error(monkeypatch, tmp_path, water_project):
    monkeypatch.setenv("GEOORCA_JOBS_DIR", str(tmp_path))
    monkeypatch.setenv("GEOORCA_ORCA_PATH", "orca")
    body = {
        "mode": "orca",
        "calculationKind": "reaction-path",
        "reactant": water_project.model_dump(by_alias=True, mode="json"),
        "reactionPathSettings": {"interpolation": "idpp", "imageCount": 8},
    }
    with TestClient(app) as client:
        response = client.post("/api/jobs", json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "PRODUCT_ENDPOINT_REQUIRED"


def test_api_rejects_nonfinite_endpoint_coordinates(monkeypatch, tmp_path, water_project):
    monkeypatch.setenv("GEOORCA_JOBS_DIR", str(tmp_path))
    monkeypatch.setenv("GEOORCA_ORCA_PATH", "orca")
    product = product_from(water_project).model_dump(by_alias=True, mode="json")
    product["atoms"][1]["position"][0] = "NaN"
    body = {
        "mode": "orca",
        "calculationKind": "reaction-path",
        "reactant": water_project.model_dump(by_alias=True, mode="json"),
        "product": product,
    }
    with TestClient(app) as client:
        response = client.post("/api/jobs", json=body)
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][-1] == "position"


def test_real_opi_writes_typed_neb_input(tmp_path, water_project):
    pytest.importorskip("opi")
    reactant = tmp_path / "reactant-optimized.xyz"
    product = tmp_path / "product-optimized.xyz"
    reactant.write_text("3\nr\nO 0 0 0\nH .9 0 0\nH -.2 .9 0\n", encoding="utf-8")
    product.write_text("3\np\nO 0 0 0\nH .9 0 0\nH -.2 1.2 0\n", encoding="utf-8")
    calculator = OpiAdapter().build_neb_calculator(
        reactant,
        product,
        water_project,
        ReactionPathSettings(imageCount=8),
        tmp_path,
    )
    calculator.write_input()
    text = (tmp_path / "reaction.inp").read_text(encoding="utf-8").lower()
    assert "!r2scan-3c" in text
    assert "!neb" in text
    assert "nimages 8" in text
    assert "interpolation idpp" in text
    assert 'neb_end_xyzfile "product-optimized.xyz"' in text
    assert "*xyzfile 0 1 reactant-optimized.xyz" in text
    single = OpiAdapter().build_calculator(water_project, tmp_path, basename="single-regression")
    single.write_input()
    single_text = (tmp_path / "single-regression.inp").read_text(encoding="utf-8").lower()
    assert "!r2scan-3c" in single_text and "!opt" in single_text
    assert "!neb" not in single_text and "%neb" not in single_text


def test_reaction_job_runs_endpoint_opt_then_neb_and_builds_manifest(
    tmp_path, water_project, monkeypatch
):
    product = product_from(water_project)
    calls: list[str] = []

    def fake_optimize(self, project, _workdir, *, basename, **_kwargs):
        calls.append(basename)
        return project

    def fake_execute(calc, workdir, **_kwargs):
        calls.append(calc.basename)
        assert calls == ["reactant-endpoint", "product-endpoint", "reaction"]
        (workdir / "reaction.out").write_bytes(
            b"NEB CONVERGED\nHURRAY\n****ORCA TERMINATED NORMALLY****\n"
        )
        (workdir / "reaction_MEP_trj.xyz").write_text(
            trajectory_text(water_project, product), encoding="utf-8"
        )

    monkeypatch.setattr(OpiAdapter, "optimize_endpoint", fake_optimize)
    monkeypatch.setattr(OpiAdapter, "_execute", staticmethod(fake_execute))
    monkeypatch.setenv("GEOORCA_JOBS_DIR", str(tmp_path))
    monkeypatch.setenv("GEOORCA_ORCA_PATH", "orca")
    body = {
        "mode": "orca",
        "calculationKind": "reaction-path",
        "reactant": water_project.model_dump(by_alias=True, mode="json"),
        "product": product.model_dump(by_alias=True, mode="json"),
        "reactionPathSettings": {"interpolation": "idpp", "imageCount": 8},
    }
    with TestClient(app) as client:
        created = client.post("/api/jobs", json=body)
        assert created.status_code == 202
        job_id = created.json()["id"]
        deadline = time.time() + 4
        while time.time() < deadline:
            finished = client.get(f"/api/jobs/{job_id}").json()
            if finished["state"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                break
            time.sleep(0.02)
        assert finished["state"] == "SUCCEEDED"
        assert finished["calculationKind"] == "reaction-path"
        playback = client.get(f"/api/jobs/{job_id}/reaction-path")
        single_result = client.get(f"/api/jobs/{job_id}/result")

    folder = tmp_path / job_id
    assert calls == ["reactant-endpoint", "product-endpoint", "reaction"]
    assert (folder / "reactant-project.json").is_file()
    assert (folder / "product-project.json").is_file()
    assert (folder / "reactant-optimized.xyz").is_file()
    assert (folder / "product-optimized.xyz").is_file()
    assert (folder / "reaction.inp").is_file()
    assert (folder / "reaction-path.json").is_file()
    assert not (folder / "result.json").exists()
    manifest = json.loads((folder / "reaction-path.json").read_text(encoding="utf-8"))
    assert manifest["sourceType"] == "neb"
    assert len(manifest["images"]) == 2
    assert playback.status_code == 200
    assert len(playback.json()["path"]["images"]) == 2
    assert single_result.status_code == 409
    assert single_result.json()["detail"]["code"] == "RESULT_NOT_AVAILABLE_FOR_REACTION_PATH"


def test_missing_final_neb_trajectory_fails_reaction_job(tmp_path, water_project, monkeypatch):
    product = product_from(water_project)

    monkeypatch.setattr(
        OpiAdapter,
        "optimize_endpoint",
        lambda self, project, _workdir, **_kwargs: project,
    )

    def fake_execute(calc, workdir, **_kwargs):
        (workdir / "reaction.out").write_bytes(
            b"NEB CONVERGED\nHURRAY\n****ORCA TERMINATED NORMALLY****\n"
        )

    monkeypatch.setattr(OpiAdapter, "_execute", staticmethod(fake_execute))
    manager = JobManager(LocalSettings(jobs_dir=str(tmp_path), orca_path="orca"))
    record = manager.create(
        water_project,
        JobMode.ORCA,
        calculation_kind=CalculationKind.REACTION_PATH,
        product=product,
    )
    finished = wait_terminal(manager, record.id)
    assert finished.state == JobState.FAILED
    assert finished.error_code == "FINAL_NEB_TRAJECTORY_MISSING"
    assert not (tmp_path / str(record.id) / "reaction-path.json").exists()
    manager.executor.shutdown()


def test_endpoint_optimization_failures_identify_the_failed_side(
    tmp_path, water_project, monkeypatch
):
    product = product_from(water_project)
    count = 0

    def fail_second(self, project, _workdir, **_kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise ChemistryError("GEOMETRY_NOT_CONVERGED", "product did not converge")
        return project

    monkeypatch.setattr(OpiAdapter, "optimize_endpoint", fail_second)
    with pytest.raises(ChemistryError) as error:
        OpiAdapter().run_reaction_path(
            water_project,
            product,
            tmp_path,
            settings=ReactionPathSettings(),
            orca_path="orca",
            cancel_event=Event(),
        )
    assert error.value.code == "PRODUCT_OPTIMIZATION_FAILED"
