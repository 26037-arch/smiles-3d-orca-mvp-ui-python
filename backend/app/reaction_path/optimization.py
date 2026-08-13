from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..models import (
    CalculatedAtom,
    CalculatedImage,
    MoleculeProject,
    Orbital,
    ReactionPathResult,
    ScfIteration,
)
from .errors import ReactionPathError
from .geometry import align_path, normalized_path_coordinate
from .importer import HARTREE_TO_KJ_MOL, ParsedFrame, _source_metadata, parse_multi_xyz


_FLOAT = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
_CYCLE = re.compile(r"GEOMETRY OPTIMIZATION CYCLE\s+(\d+)", re.IGNORECASE)
_SCF_HEADER = re.compile(r"Iteration\s+Energy\s*\(Eh\)\s+Delta-E", re.IGNORECASE)
_SCF_ROW = re.compile(
    rf"^\s*(?P<iteration>\d+)\s+(?P<energy>{_FLOAT})\s+(?P<delta>{_FLOAT})"
    rf"\s+(?P<rms>{_FLOAT})\s+(?P<max>{_FLOAT})(?:\s+(?P<error>{_FLOAT}))?"
)


@dataclass(frozen=True)
class ScfCycle:
    iterations: list[ScfIteration]
    converged: bool


def parse_scf_history(path: Path) -> list[ScfCycle]:
    """Parse SCF iteration tables per ORCA geometry cycle.

    Missing optional columns are kept as ``None``. Text is decoded explicitly so
    the Windows process locale can never turn an otherwise valid ORCA output into
    a parser failure.
    """

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise ReactionPathError("SCF_HISTORY_PARSE_WARNING", str(exc)) from exc

    cycles: list[ScfCycle] = []
    current: list[ScfIteration] | None = None
    in_table = False
    table_kind: str | None = None
    converged = False
    for line in lines:
        if "FINAL ENERGY EVALUATION AT THE STATIONARY POINT" in line.upper():
            if current is not None:
                cycles.append(ScfCycle(current, converged))
            current = []
            in_table = False
            table_kind = None
            converged = False
            continue
        if _CYCLE.search(line):
            if current is not None:
                cycles.append(ScfCycle(current, converged))
            current = []
            in_table = False
            table_kind = None
            converged = False
            continue
        if current is None:
            continue
        if "SCF CONVERGED AFTER" in line.upper():
            converged = True
        if _SCF_HEADER.search(line):
            in_table = True
            table_kind = "max-gradient" if "MAXGRAD" in line.upper() else "diis"
            continue
        if not in_table:
            continue
        match = _SCF_ROW.match(line)
        if not match:
            if "FINAL SINGLE POINT ENERGY" in line.upper() or "SCF CONVERGED" in line.upper():
                in_table = False
            continue
        values = match.groupdict()
        optional = _number(values.get("error"))
        current.append(
            ScfIteration(
                iteration=int(values["iteration"]),
                energyHartree=_number(values["energy"]),
                deltaEnergyHartree=_number(values["delta"]),
                rmsDensity=_number(values["rms"]),
                maxDensity=_number(values["max"]),
                diisError=optional if table_kind == "diis" else None,
                maxGradient=optional if table_kind == "max-gradient" else None,
            )
        )
    if current is not None:
        cycles.append(ScfCycle(current, converged))
    return cycles


def optimization_frames(output: object, trajectory: Path, project: MoleculeProject) -> list[ParsedFrame]:
    """Prefer OPI geometries, then the immutable ORCA optimization trajectory."""

    frames = _opi_frames(output, [atom.element for atom in project.atoms])
    if frames and trajectory.is_file():
        try:
            trajectory_frames = parse_multi_xyz(trajectory, minimum_frames=1)
        except ReactionPathError:
            trajectory_frames = []
        if len(trajectory_frames) == len(frames):
            frames = [
                ParsedFrame(
                    frame.elements,
                    frame.coordinates,
                    frame.energy_hartree
                    if frame.energy_hartree is not None
                    else trajectory_frames[index].energy_hartree,
                )
                for index, frame in enumerate(frames)
            ]
    if not frames:
        try:
            frames = parse_multi_xyz(trajectory, minimum_frames=1)
        except ReactionPathError as exc:
            frames = _output_frames(output, [atom.element for atom in project.atoms])
            if not frames:
                code = (
                    "OPTIMIZATION_TRAJECTORY_MISSING"
                    if exc.code
                    in {"REACTION_PATH_SOURCE_UNREADABLE", "REACTION_PATH_SOURCE_MISSING"}
                    else "OPTIMIZATION_TRAJECTORY_INVALID"
                )
                raise ReactionPathError(code, exc.detail) from exc
    initial = ParsedFrame(
        elements=[atom.element for atom in project.atoms],
        coordinates=[tuple(atom.position) for atom in project.atoms],
        energy_hartree=None,
    )
    if not _same_coordinates(initial, frames[0]):
        frames.insert(0, initial)
    return frames


def build_optimization_path(
    job_dir: Path,
    project: MoleculeProject,
    frames: list[ParsedFrame],
    histories: list[ScfCycle],
    step_orbitals: list[list[Orbital]],
    step_wavefunctions: list[str | None],
    step_success: list[bool] | None = None,
) -> ReactionPathResult:
    if not frames:
        raise ReactionPathError(
            "OPTIMIZATION_TRAJECTORY_INVALID", "최적화 trajectory에 geometry step이 없습니다"
        )
    if len(step_orbitals) != len(frames) or len(step_wavefunctions) != len(frames):
        raise ReactionPathError(
            "OPTIMIZATION_POSTPROCESS_INCOMPLETE",
            "geometry와 single-point 결과 수가 일치하지 않습니다",
        )
    if step_success is not None and len(step_success) != len(frames):
        raise ReactionPathError(
            "OPTIMIZATION_POSTPROCESS_INCOMPLETE",
            "geometry와 single-point 상태 수가 일치하지 않습니다",
        )
    frames = [
        ParsedFrame(
            frame.elements,
            frame.coordinates,
            frame.energy_hartree
            if frame.energy_hartree is not None
            else histories[index].iterations[-1].energy_hartree
            if index < len(histories) and histories[index].iterations
            else None,
        )
        for index, frame in enumerate(frames)
    ]
    reference = frames[0].energy_hartree
    images: list[CalculatedImage] = []
    previous_energy: float | None = None
    for index, frame in enumerate(frames):
        history = histories[index] if index < len(histories) else ScfCycle([], False)
        energy_change = (
            None
            if previous_energy is None or frame.energy_hartree is None
            else frame.energy_hartree - previous_energy
        )
        images.append(
            CalculatedImage(
                id=f"geometry-{index}",
                index=index,
                atoms=[
                    CalculatedAtom(
                        element=element,
                        atomIndex=atom_index,
                        x=xyz[0],
                        y=xyz[1],
                        z=xyz[2],
                    )
                    for atom_index, (element, xyz) in enumerate(
                        zip(frame.elements, frame.coordinates, strict=True)
                    )
                ],
                energyHartree=frame.energy_hartree,
                energyChangeHartree=energy_change,
                relativeEnergyKjMol=(
                    None
                    if reference is None or frame.energy_hartree is None
                    else (frame.energy_hartree - reference) * HARTREE_TO_KJ_MOL
                ),
                wavefunctionRef=step_wavefunctions[index],
                orbitals=step_orbitals[index],
                scfIterations=history.iterations,
                scfConverged=history.converged,
                geometryConverged=index == len(frames) - 1,
                convergence=(
                    "unconverged"
                    if step_success is not None and not step_success[index]
                    else "converged"
                    if history.converged
                    else "unknown"
                ),
            )
        )
        if frame.energy_hartree is not None:
            previous_energy = frame.energy_hartree

    aligned = align_path(images, frames[0].elements)
    coordinates = normalized_path_coordinate(images, aligned)
    images = [
        image.model_copy(update={"reaction_coordinate": float(coordinates[index])})
        for index, image in enumerate(images)
    ]
    trajectory = job_dir / "optimization_trj.xyz"
    source = trajectory if trajectory.is_file() else job_dir / "optimization.out"
    metadata = _source_metadata(job_dir, source)
    return ReactionPathResult(
        schemaVersion=2,
        pathType="geometry-optimization",
        sourceType="orca-optimization",
        atomCount=len(frames[0].elements),
        elements=frames[0].elements,
        charge=project.total_charge,
        multiplicity=project.multiplicity,
        images=images,
        hasPhysicalTime=False,
        isPhysicalTimeTrajectory=False,
        initialGuess="PAtom",
        energyUnit="hartree",
        relativeEnergyUnit="kJ/mol",
        energyReference="first-image",
        reactionCoordinateSource="derived-aligned-cartesian",
        sourceTrajectory=metadata["path"],
        sourceMetadata=metadata,
    )


def _opi_frames(output: object, expected_elements: list[str]) -> list[ParsedFrame]:
    try:
        geometries = output.results_properties.geometries  # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        return []
    frames: list[ParsedFrame] = []
    for geometry in geometries or []:
        coords = getattr(geometry, "coordinates", None)
        if coords is None:
            coords = getattr(geometry, "coords", None)
        if coords is None:
            return []
        try:
            coordinates = [_coordinate_tuple(value) for value in list(coords)]
        except (TypeError, ValueError, KeyError):
            return []
        if len(coordinates) != len(expected_elements):
            return []
        single_point = getattr(geometry, "single_point_data", None)
        energy = getattr(single_point, "finalenergy", None)
        energy = float(energy) if energy is not None else None
        frames.append(ParsedFrame(expected_elements.copy(), coordinates, energy))
    return frames


def _output_frames(output: object, expected_elements: list[str]) -> list[ParsedFrame]:
    try:
        structure = output.get_structure(index=-1)  # type: ignore[attr-defined]
        atoms = getattr(structure, "atoms", []) if structure else []
        coordinates = [
            _coordinate_tuple(getattr(atom, "coordinates", atom)) for atom in atoms
        ]
        if len(coordinates) != len(expected_elements):
            return []
        energy = output.get_final_energy()  # type: ignore[attr-defined]
        return [
            ParsedFrame(
                expected_elements.copy(),
                coordinates,
                float(energy) if energy is not None else None,
            )
        ]
    except (AttributeError, TypeError, ValueError, KeyError):
        return []


def _same_coordinates(left: ParsedFrame, right: ParsedFrame, tolerance: float = 1e-6) -> bool:
    return left.elements == right.elements and np.allclose(
        np.asarray(left.coordinates), np.asarray(right.coordinates), atol=tolerance, rtol=0
    )


def _coordinate_tuple(value: object) -> tuple[float, float, float]:
    raw = getattr(value, "coordinates", value)
    if hasattr(raw, "x"):
        return float(raw.x), float(raw.y), float(raw.z)
    if hasattr(raw, "model_dump"):
        dumped = raw.model_dump()
        return float(dumped["x"]), float(dumped["y"]), float(dumped["z"])
    values = tuple(map(float, raw))  # type: ignore[arg-type]
    if len(values) != 3 or not all(math.isfinite(item) for item in values):
        raise ValueError("invalid coordinates")
    return values  # type: ignore[return-value]


def _number(value: str | None) -> float | None:
    if value is None:
        return None
    parsed = float(value.replace("D", "E").replace("d", "e"))
    return parsed if math.isfinite(parsed) else None
