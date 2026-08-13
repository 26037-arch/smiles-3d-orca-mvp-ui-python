from __future__ import annotations

from uuid import uuid4

from backend.app.fields import CubeFieldService
from backend.app.models import CalculationResult, Orbital, PlotField
from backend.app.wavefunction import single_wavefunction_context


def test_single_wavefunction_context_and_canonical_cube_are_shared(
    monkeypatch, tmp_path, water_project
):
    (tmp_path / "project.json").write_text(
        water_project.model_dump_json(by_alias=True), encoding="utf-8"
    )
    orbital = Orbital(
        internal_id="restricted:7",
        orca_index=7,
        display_number=8,
        energy_hartree=-0.2,
        occupancy=2,
    )
    result = CalculationResult(
        job_id=uuid4(),
        optimized_atoms=water_project.atoms,
        total_energy_hartree=-76,
        normal_termination=True,
        scf_converged=True,
        geometry_converged=True,
        orbitals=[orbital],
    )
    (tmp_path / "result.json").write_text(result.model_dump_json(), encoding="utf-8")
    (tmp_path / "electronic.gbw").write_bytes(b"persistent-wavefunction")
    generated = []

    def generate(_job_dir, gbw_path, output, _field, resolution):
        generated.append((gbw_path, output, resolution))
        output.write_text("derived cube", encoding="ascii")

    monkeypatch.setattr(CubeFieldService, "_generate_from_gbw", staticmethod(generate))
    service = CubeFieldService()
    context = single_wavefunction_context(tmp_path)
    field = PlotField(
        field="mo",
        orbital_internal_id=orbital.internal_id,
        orbital_index=orbital.orca_index,
        spin=orbital.spin,
    )

    first, first_hit = service.ensure_context(tmp_path, context, field, resolution=40)
    second, second_hit = service.ensure_context(tmp_path, context, field, resolution=40)

    assert context.source_type == "single"
    assert context.gbw_path == (tmp_path / "electronic.gbw").resolve()
    assert first == second
    assert not first_hit and second_hit
    assert generated == [((tmp_path / "electronic.gbw").resolve(), first, 40)]
