from __future__ import annotations

from dataclasses import dataclass
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from threading import Event
from typing import Callable

from ..models import (
    CalculationResult,
    MoleculeProject,
    Orbital,
    ReactionPathResult,
    ReactionPathSettings,
)
from ..reaction_path.errors import ReactionPathError
from ..reaction_path.importer import ReactionPathManifestGenerator
from ..reaction_path.optimization import (
    build_optimization_path,
    optimization_frames,
    parse_scf_history,
)
from .encoding import install_opi_utf8_compatibility
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
            from opi.input.simple_keywords import Dft, Scf, Task
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
        calculator.input.add_simple_keywords(Dft.R2SCAN_3C, Scf.PATOM, Task.OPT)
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
        install_opi_utf8_compatibility()
        optimized_project, output = self._optimize_project(
            project,
            workdir,
            basename="optimization",
            orca_path=orca_path,
            cancel_event=cancel_event,
            process_started=process_started,
            label="구조",
        )
        positions = [atom.position for atom in optimized_project.atoms]
        atoms = optimized_project.atoms

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

        orbitals = _extract_orbitals(electronic_output)
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

    def optimize_endpoint(
        self,
        project: MoleculeProject,
        workdir: Path,
        *,
        basename: str,
        orca_path: str,
        cancel_event: Event,
        process_started: Callable[[subprocess.Popen[str]], None] | None = None,
        label: str,
    ) -> MoleculeProject:
        optimized, _ = self._optimize_project(
            project,
            workdir,
            basename=basename,
            orca_path=orca_path,
            cancel_event=cancel_event,
            process_started=process_started,
            label=label,
        )
        return optimized

    def _optimize_project(
        self,
        project: MoleculeProject,
        workdir: Path,
        *,
        basename: str,
        orca_path: str,
        cancel_event: Event,
        process_started: Callable[[subprocess.Popen[str]], None] | None,
        label: str,
    ) -> tuple[MoleculeProject, object]:
        calc = self.build_calculator(project, workdir, basename=basename)
        self.log(f"{label} endpoint OPI 입력 작성" if label != "구조" else "OPI 입력 작성")
        calc.write_input()
        self.log(f"{label} endpoint 최적화 실행" if label != "구조" else "ORCA 구조 최적화 실행")
        self._execute(
            calc,
            workdir,
            orca_path=orca_path,
            cancel_event=cancel_event,
            process_started=process_started,
        )
        output = calc.get_output()
        _check_output_status(output, require_geometry=True)
        output.parse()
        positions = _optimized_positions(output, workdir, basename, len(project.atoms))
        atoms = [
            atom.model_copy(update={"position": positions[index]})
            for index, atom in enumerate(project.atoms)
        ]
        return project.model_copy(update={"atoms": atoms}), output

    def build_path_single_point(
        self,
        project: MoleculeProject,
        positions: list[tuple[float, float, float]],
        workdir: Path,
        *,
        basename: str,
        previous_gbw: Path | None,
    ):
        """Build one immutable per-geometry electronic-structure calculation."""

        try:
            from opi.core import Calculator
            from opi.input.simple_keywords import (
                BasisSet,
                Dft,
                DispersionCorrection,
                Scf,
                Task,
            )
            from opi.input.structures.structure import Structure
        except ImportError as exc:
            raise ChemistryError("OPI_UNAVAILABLE", "OPI 2.0을 import할 수 없습니다") from exc

        calculator = Calculator(
            basename=basename, working_dir=workdir, version_check=False
        )
        calculator.structure = Structure.from_lists(
            [atom.element for atom in project.atoms],
            positions,
            charge=project.total_charge,
            multiplicity=project.multiplicity,
        )
        if project.calculation_preset == "standard":
            calculator.input.add_simple_keywords(
                Dft.PBE0,
                DispersionCorrection.D4,
                BasisSet.DEF2_SVP,
                Scf.TIGHTSCF,
                Task.SP,
            )
        else:
            calculator.input.add_simple_keywords(Dft.R2SCAN_3C, Task.SP)
        if previous_gbw is None:
            calculator.input.add_simple_keywords(Scf.PATOM)
        else:
            calculator.input.add_simple_keywords(Scf.MOREAD)
            calculator.input.moinp = previous_gbw
        calculator.input.ncores = 1
        return calculator

    def run_optimization_path(
        self,
        project: MoleculeProject,
        workdir: Path,
        *,
        orca_path: str,
        cancel_event: Event,
        process_started: Callable[[subprocess.Popen[str]], None] | None = None,
        stage: Callable[[float, str], None] | None = None,
    ) -> ReactionPathResult:
        """Run the real r2SCAN-3c optimization and persist its actual geometries."""

        install_opi_utf8_compatibility()
        notify = stage or (lambda _progress, message: self.log(message))
        notify(0.12, "r2SCAN-3c 구조 최적화")
        calculator = self.build_calculator(project, workdir, basename="optimization")
        calculator.write_input()
        self._execute(
            calculator,
            workdir,
            orca_path=orca_path,
            cancel_event=cancel_event,
            process_started=process_started,
        )
        output = calculator.get_output()
        _check_output_status(output, require_geometry=True)
        output.parse()

        notify(0.58, "실제 최적화 geometry와 SCF 이력 수집")
        trajectory = workdir / "optimization_trj.xyz"
        try:
            frames = optimization_frames(output, trajectory, project)
        except ReactionPathError as exc:
            raise ChemistryError(exc.code, exc.detail) from exc
        try:
            histories = parse_scf_history(workdir / "optimization.out")
        except ReactionPathError as exc:
            self.log(f"SCF 이력 파싱 경고 [{exc.code}]: {exc.detail}")
            histories = []

        orbitals_by_step: list[list[Orbital]] = []
        wavefunctions: list[str | None] = []
        step_success: list[bool] = []
        previous_gbw: Path | None = None
        total = len(frames)
        for index, frame in enumerate(frames):
            if cancel_event.is_set():
                raise ChemistryError("CANCELLED", "사용자가 계산을 취소했습니다")
            notify(
                0.62 + 0.30 * ((index + 1) / total),
                f"geometry {index + 1}/{total} single point",
            )
            basename = f"step-{index:03d}"
            try:
                single_point = self.build_path_single_point(
                    project,
                    frame.coordinates,
                    workdir,
                    basename=basename,
                    previous_gbw=previous_gbw,
                )
                single_point.write_input()
                self._execute(
                    single_point,
                    workdir,
                    orca_path=orca_path,
                    cancel_event=cancel_event,
                    process_started=process_started,
                )
                step_output = single_point.get_output()
                _check_output_status(
                    step_output, require_geometry=False, single_point=True
                )
                step_output.parse()
                gbw = workdir / f"{basename}.gbw"
                if not gbw.is_file():
                    raise ChemistryError(
                        "STEP_WAVEFUNCTION_MISSING",
                        f"{basename}.gbw를 찾을 수 없습니다",
                    )
                orbitals_by_step.append(_extract_orbitals(step_output))
                wavefunctions.append(gbw.name)
                step_success.append(True)
                previous_gbw = gbw
            except ChemistryError as exc:
                if exc.code == "CANCELLED":
                    raise
                if index in {0, total - 1}:
                    code = (
                        "INITIAL_SINGLE_POINT_FAILED"
                        if index == 0
                        else "FINAL_SINGLE_POINT_FAILED"
                    )
                    raise ChemistryError(code, exc.detail) from exc
                self.log(
                    f"geometry {index + 1} single point 건너뜀 "
                    f"[{exc.code}]: {exc.detail}"
                )
                orbitals_by_step.append([])
                wavefunctions.append(None)
                step_success.append(False)

        try:
            result = build_optimization_path(
                workdir,
                project,
                frames,
                histories,
                orbitals_by_step,
                wavefunctions,
                step_success,
            )
        except ReactionPathError as exc:
            raise ChemistryError(exc.code, exc.detail) from exc
        ReactionPathManifestGenerator._atomic_write(
            workdir / "reaction-path.json",
            result.model_dump(by_alias=True, mode="json"),
        )
        notify(0.96, "최적화 경로 manifest 저장")
        return result

    def build_neb_calculator(
        self,
        reactant_xyz: Path,
        product_xyz: Path,
        project: MoleculeProject,
        settings: ReactionPathSettings,
        workdir: Path,
    ):
        try:
            from opi.core import Calculator
            from opi.input.blocks import BlockNeb
            from opi.input.simple_keywords import Dft, Neb
            from opi.input.structures import XyzFile
        except ImportError as exc:
            raise ChemistryError("OPI_UNAVAILABLE", "OPI 2.0의 NEB API를 import할 수 없습니다") from exc
        calculator = Calculator(
            basename="reaction", working_dir=workdir, version_check=False
        )
        calculator.structure = XyzFile(
            reactant_xyz,
            charge=project.total_charge,
            multiplicity=project.multiplicity,
        )
        calculator.input.add_simple_keywords(Dft.R2SCAN_3C, Neb.NEB)
        calculator.input.add_blocks(
            BlockNeb(
                nimages=settings.image_count,
                interpolation=settings.interpolation,
                neb_end_xyzfile=product_xyz.name,
            )
        )
        calculator.input.ncores = 1
        return calculator

    def run_neb_path(
        self,
        reactant: MoleculeProject,
        product: MoleculeProject,
        workdir: Path,
        *,
        settings: ReactionPathSettings,
        orca_path: str,
        cancel_event: Event,
        process_started: Callable[[subprocess.Popen[str]], None] | None = None,
        stage: Callable[[float, str], None] | None = None,
    ) -> Path:
        install_opi_utf8_compatibility()
        notify = stage or (lambda _progress, message: self.log(message))
        try:
            notify(0.12, "반응물 endpoint 최적화")
            optimized_reactant = self.optimize_endpoint(
                reactant,
                workdir,
                basename="reactant-endpoint",
                orca_path=orca_path,
                cancel_event=cancel_event,
                process_started=process_started,
                label="반응물",
            )
        except ChemistryError as exc:
            if exc.code == "CANCELLED":
                raise
            raise ChemistryError("REACTANT_OPTIMIZATION_FAILED", exc.detail) from exc
        reactant_xyz = workdir / "reactant-optimized.xyz"
        _write_xyz(reactant_xyz, optimized_reactant)
        try:
            notify(0.38, "생성물 endpoint 최적화")
            optimized_product = self.optimize_endpoint(
                product,
                workdir,
                basename="product-endpoint",
                orca_path=orca_path,
                cancel_event=cancel_event,
                process_started=process_started,
                label="생성물",
            )
        except ChemistryError as exc:
            if exc.code == "CANCELLED":
                raise
            raise ChemistryError("PRODUCT_OPTIMIZATION_FAILED", exc.detail) from exc
        product_xyz = workdir / "product-optimized.xyz"
        _write_xyz(product_xyz, optimized_product)

        notify(0.62, "초기 경로 생성 (IDPP)")
        calculator = self.build_neb_calculator(
            reactant_xyz, product_xyz, optimized_reactant, settings, workdir
        )
        calculator.write_input()
        notify(0.68, "NEB 계산")
        try:
            self._execute(
                calculator,
                workdir,
                orca_path=orca_path,
                cancel_event=cancel_event,
                process_started=process_started,
            )
        except ChemistryError as exc:
            if exc.code == "CANCELLED":
                raise
            raise ChemistryError("NEB_FAILED", exc.detail) from exc
        _check_neb_output(workdir / "reaction.out")
        trajectory = workdir / "reaction_MEP_trj.xyz"
        if not trajectory.is_file():
            raise ChemistryError(
                "FINAL_NEB_TRAJECTORY_MISSING",
                "NEB가 종료됐지만 reaction_MEP_trj.xyz를 찾을 수 없습니다",
            )
        return trajectory

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


def _extract_orbitals(output: object) -> list[Orbital]:
    mo_groups = output.get_mos() or {}  # type: ignore[attr-defined]
    orbitals: list[Orbital] = []
    for key, spin in (("mo", "restricted"), ("alpha", "alpha"), ("beta", "beta")):
        channel = mo_groups.get(key, [])
        occupied = [i for i, mo in enumerate(channel) if float(mo.occupancy) > 0]
        virtual = [i for i, mo in enumerate(channel) if float(mo.occupancy) == 0]
        homo = occupied[-1] if occupied else None
        lumo = virtual[0] if virtual else None
        orbitals.extend(
            Orbital(
                internal_id=f"{spin}:{i}",
                orca_index=i,
                display_number=i + 1,
                energy_hartree=float(mo.orbitalenergy),
                occupancy=float(mo.occupancy),
                spin=spin,
                label="HOMO" if i == homo else "LUMO" if i == lumo else None,
            )
            for i, mo in enumerate(channel)
        )
    return orbitals


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


def _check_neb_output(path: Path) -> None:
    try:
        contents = path.read_bytes()
    except OSError as exc:
        raise ChemistryError("NEB_FAILED", "NEB 출력 파일을 읽을 수 없습니다") from exc
    if b"****ORCA TERMINATED NORMALLY****" not in contents:
        raise ChemistryError("NEB_FAILED", "ORCA NEB가 정상 종료하지 않았습니다")
    upper = contents.upper()
    if b"HURRAY" not in upper and not re.search(rb"NEB[^\r\n]{0,80}CONVERGED", upper):
        raise ChemistryError("NEB_NOT_CONVERGED", "ORCA NEB 수렴 표식을 찾지 못했습니다")


def _optimized_positions(
    output: object, workdir: Path, basename: str, atom_count: int
) -> list[tuple[float, float, float]]:
    geometries = output.results_properties.geometries  # type: ignore[attr-defined]
    final_geometry = geometries[-1]
    coords = getattr(final_geometry, "coordinates", None)
    if coords is None:
        coords = getattr(final_geometry, "coords", None)
    if coords is not None:
        coords = list(coords)
    if coords is None:
        optimized_structure = output.get_structure(index=-1)  # type: ignore[attr-defined]
        atoms_from_opi = getattr(optimized_structure, "atoms", []) if optimized_structure else []
        coords = [getattr(atom, "coordinates", None) for atom in atoms_from_opi]
    if not coords or any(coord is None for coord in coords):
        candidates = [
            workdir / f"{basename}.xyz",
            workdir / f"{basename}_trj.xyz",
        ]
        source = next((path for path in candidates if path.is_file()), None)
        if source is None:
            raise ChemistryError("OPTIMIZED_COORDINATES_MISSING", "최적 좌표 파일을 찾지 못했습니다")
        coords = _read_last_xyz_positions(source)
    positions = [_coordinate_tuple(coordinate) for coordinate in coords]
    if len(positions) != atom_count:
        raise ChemistryError("ATOM_ORDER_MISMATCH", "최적 좌표의 원자 수가 입력과 다릅니다")
    return positions


def _read_xyz_positions(path: Path) -> list[tuple[float, float, float]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[2:]
    return [tuple(map(float, line.split()[1:4])) for line in lines if len(line.split()) >= 4]


def _read_last_xyz_positions(path: Path) -> list[tuple[float, float, float]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    cursor = 0
    last: list[tuple[float, float, float]] = []
    while cursor < len(lines):
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        if cursor >= len(lines):
            break
        try:
            count = int(lines[cursor].strip())
        except ValueError as exc:
            raise ChemistryError("OPTIMIZED_COORDINATES_MISSING", "최적 XYZ가 손상되었습니다") from exc
        if cursor + count + 1 >= len(lines):
            raise ChemistryError("OPTIMIZED_COORDINATES_MISSING", "최적 XYZ가 중간에서 잘렸습니다")
        frame = lines[cursor + 2 : cursor + 2 + count]
        try:
            last = [tuple(map(float, row.split()[1:4])) for row in frame]
        except ValueError as exc:
            raise ChemistryError("OPTIMIZED_COORDINATES_MISSING", "최적 XYZ 좌표가 잘못되었습니다") from exc
        cursor += count + 2
    return last


def _coordinate_tuple(value) -> tuple[float, float, float]:
    raw = getattr(value, "coordinates", value)
    if hasattr(raw, "x"):
        return float(raw.x), float(raw.y), float(raw.z)
    if hasattr(raw, "model_dump"):
        dumped = raw.model_dump()
        return float(dumped["x"]), float(dumped["y"]), float(dumped["z"])
    return tuple(map(float, raw))


def _write_xyz(path: Path, project: MoleculeProject) -> None:
    rows = [str(len(project.atoms)), project.name]
    rows.extend(
        f"{atom.element} {atom.position[0]:.12f} {atom.position[1]:.12f} "
        f"{atom.position[2]:.12f}"
        for atom in project.atoms
    )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


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
