from __future__ import annotations

from dataclasses import dataclass
import os
import signal
import subprocess
import time
from pathlib import Path
from threading import Event
from typing import Callable

from ..models import CalculationResult, MoleculeProject, Orbital
from .presets import get_preset


class ChemistryError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass
class OpiAdapter:
    """The only module that imports OPI. Tested independently from API and jobs."""

    log: Callable[[str], None] = print

    def build_calculator(self, project: MoleculeProject, workdir: Path, basename: str = "optimization"):
        try:
            from opi.core import Calculator
            from opi.input.simple_keywords import Dft, Task
            from opi.input.structures.structure import Structure
        except ImportError as exc:
            raise ChemistryError("OPI_UNAVAILABLE", "OPI 2.0을 import할 수 없습니다") from exc
        get_preset(project.calculation_preset)
        structure = Structure.from_lists(
            [atom.element for atom in project.atoms],
            [tuple(atom.position) for atom in project.atoms],
            charge=project.total_charge,
            multiplicity=project.multiplicity,
        )
        # Version compatibility is checked by the application diagnostics against the
        # configured executable; execution itself uses that exact path below.
        calculator = Calculator(basename=basename, working_dir=workdir, version_check=False)
        calculator.structure = structure
        # Both MVP presets share the documented r2SCAN-3c optimization stage.
        calculator.input.add_simple_keywords(Dft.R2SCAN_3C, Task.OPT)
        calculator.input.ncores = 1
        return calculator

    def run(
        self,
        project: MoleculeProject,
        workdir: Path,
        job_id,
        *,
        orca_path: str,
        cancel_event: Event,
        process_started: Callable[[subprocess.Popen[str]], None] | None = None,
    ) -> CalculationResult:
        calc = self.build_calculator(project, workdir)
        self.log("OPI 입력 작성")
        calc.write_input()
        self.log("ORCA 구조 최적화 실행")
        self._execute(
            calc, workdir, orca_path=orca_path, cancel_event=cancel_event,
            process_started=process_started,
        )
        output = calc.get_output()
        _check_output_status(output, require_geometry=True)
        output.parse()
        geometries = output.results_properties.geometries
        final_geometry = geometries[-1]
        coords = getattr(final_geometry, "coordinates", None) or getattr(final_geometry, "coords", None)
        if coords is None:
            optimized_structure = output.get_structure(index=-1)
            atoms_from_opi = getattr(optimized_structure, "atoms", []) if optimized_structure else []
            coords = [getattr(atom, "coordinates", None) for atom in atoms_from_opi]
        if not coords or any(coord is None for coord in coords):
            xyz_candidates = sorted(workdir.glob("*.xyz"), key=lambda p: p.stat().st_mtime)
            if not xyz_candidates:
                raise ChemistryError("OPTIMIZED_COORDINATES_MISSING", "최적 좌표 파일을 찾지 못했습니다")
            coords = _read_xyz_positions(xyz_candidates[-1])
        positions = [_coordinate_tuple(c) for c in coords]
        if len(positions) != len(project.atoms):
            raise ChemistryError("ATOM_ORDER_MISMATCH", "최적 좌표의 원자 수가 입력과 다릅니다")
        atoms = [atom.model_copy(update={"position": positions[i]}) for i, atom in enumerate(project.atoms)]

        electronic_output = output
        if project.calculation_preset == "standard":
            self.log("표준 프리셋 PBE0-D4/def2-SVP single point 구성")
            electronic = self._build_standard_single_point(project, positions, workdir)
            electronic.write_input()
            self._execute(
                electronic, workdir, orca_path=orca_path, cancel_event=cancel_event,
                process_started=process_started,
            )
            electronic_output = electronic.get_output()
            _check_output_status(
                electronic_output, require_geometry=False, single_point=True
            )
            electronic_output.parse()

        mo_groups = electronic_output.get_mos() or {}
        orbitals: list[Orbital] = []
        for key, spin in (("mo", "restricted"), ("alpha", "alpha"), ("beta", "beta")):
            channel = mo_groups.get(key, [])
            occupied_indices = [i for i, mo in enumerate(channel) if float(mo.occupancy) > 0]
            virtual_indices = [i for i, mo in enumerate(channel) if float(mo.occupancy) == 0]
            homo_index = occupied_indices[-1] if occupied_indices else None
            lumo_index = virtual_indices[0] if virtual_indices else None
            orbitals.extend(
                Orbital(
                    internal_id=f"{spin}:{i}", orca_index=i, display_number=i + 1,
                    energy_hartree=float(mo.orbitalenergy), occupancy=float(mo.occupancy),
                    spin=spin,
                    label="HOMO" if i == homo_index else "LUMO" if i == lumo_index else None,
                )
                for i, mo in enumerate(channel)
            )
        homo = max((o for o in orbitals if o.occupancy > 0), key=lambda o: o.energy_hartree, default=None)
        lumo = min((o for o in orbitals if o.occupancy == 0), key=lambda o: o.energy_hartree, default=None)
        energy = electronic_output.get_final_energy()
        if energy is None:
            energy = electronic_output.results_properties.geometries[-1].single_point_data.finalenergy
        return CalculationResult(
            job_id=job_id, optimized_atoms=atoms, total_energy_hartree=float(energy),
            normal_termination=True, scf_converged=True, geometry_converged=True,
            orbitals=orbitals, homo_internal_id=homo.internal_id if homo else None,
            lumo_internal_id=lumo.internal_id if lumo else None,
        )

    def _build_standard_single_point(self, project: MoleculeProject, positions, workdir: Path):
        try:
            from opi.core import Calculator
            from opi.input.simple_keywords import BasisSet, Dft, DispersionCorrection, Scf, Task
            from opi.input.structures.structure import Structure
        except ImportError as exc:
            raise ChemistryError("OPI_UNAVAILABLE", "OPI 2.0을 import할 수 없습니다") from exc
        structure = Structure.from_lists(
            [atom.element for atom in project.atoms], positions,
            charge=project.total_charge, multiplicity=project.multiplicity,
        )
        calculator = Calculator(basename="electronic", working_dir=workdir, version_check=False)
        calculator.structure = structure
        calculator.input.add_simple_keywords(
            Dft.PBE0, DispersionCorrection.D4, BasisSet.DEF2_SVP, Scf.TIGHTSCF, Task.SP
        )
        calculator.input.ncores = 1
        return calculator

    @staticmethod
    def _execute(
        calc, workdir: Path, *, orca_path: str, cancel_event: Event,
        process_started: Callable[[subprocess.Popen[str]], None] | None,
    ) -> None:
        input_path = calc.inpfile
        if input_path is None:
            raise ChemistryError("INPUT_MISSING", "OPI가 ORCA 입력 파일을 만들지 못했습니다")
        output_path = workdir / f"{calc.basename}.out"
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        with output_path.open("w", encoding="utf-8") as output_file:
            process = subprocess.Popen(
                [orca_path, input_path.name], cwd=workdir, stdout=output_file,
                stderr=subprocess.STDOUT, text=True, shell=False,
                creationflags=creationflags, start_new_session=os.name != "nt",
            )
            if process_started:
                process_started(process)
            while process.poll() is None:
                if cancel_event.wait(0.2):
                    _terminate_process_tree(process)
                    raise ChemistryError("CANCELLED", "사용자가 계산을 취소했습니다")
                time.sleep(0.05)
        if process.returncode != 0:
            raise ChemistryError("ABNORMAL_TERMINATION", f"ORCA 종료 코드: {process.returncode}")


def _check_output_status(
    output: object, *, require_geometry: bool, single_point: bool = False
) -> None:
    """Check ASCII ORCA status markers without locale-dependent text decoding.

    ORCA 6.1 output contains UTF-8 punctuation in its citation section. OPI 2.0's
    grep helpers open the file using the Windows locale (commonly cp949), which can
    raise ``UnicodeDecodeError`` even when the calculation terminated normally.
    The convergence markers themselves are ASCII, so searching the raw bytes is
    both sufficient and independent of the host locale.
    """
    try:
        output_path = Path(output.get_outfile())  # type: ignore[attr-defined]
        contents = output_path.read_bytes()
    except (AttributeError, OSError, TypeError) as exc:
        raise ChemistryError("OUTPUT_MISSING", "ORCA 출력 파일을 읽을 수 없습니다") from exc

    if b"****ORCA TERMINATED NORMALLY****" not in contents:
        code = "SINGLE_POINT_ABNORMAL_TERMINATION" if single_point else "ABNORMAL_TERMINATION"
        detail = (
            "표준 single point가 정상 종료하지 않았습니다"
            if single_point
            else "ORCA가 정상 종료하지 않았습니다"
        )
        raise ChemistryError(code, detail)
    if b"SUCCESS" not in contents:
        code = "SINGLE_POINT_SCF_NOT_CONVERGED" if single_point else "SCF_NOT_CONVERGED"
        detail = (
            "표준 single point SCF가 수렴하지 않았습니다"
            if single_point
            else "SCF가 수렴하지 않았습니다"
        )
        raise ChemistryError(code, detail)
    if require_geometry and b"HURRAY" not in contents:
        raise ChemistryError("GEOMETRY_NOT_CONVERGED", "구조 최적화가 수렴하지 않았습니다")


def _read_xyz_positions(path: Path) -> list[tuple[float, float, float]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[2:]
    return [tuple(map(float, line.split()[1:4])) for line in lines if len(line.split()) >= 4]


def _coordinate_tuple(value) -> tuple[float, float, float]:
    raw = getattr(value, "coordinates", value)
    if hasattr(raw, "x"):
        return float(raw.x), float(raw.y), float(raw.z)
    if hasattr(raw, "model_dump"):
        dumped = raw.model_dump()
        return float(dumped["x"]), float(dumped["y"]), float(dumped["z"])
    return tuple(map(float, raw))


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True, shell=False, timeout=10,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
