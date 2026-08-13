from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .models import Atom, CalculationResult, MoleculeProject, Orbital, ReactionPathPlayback


@dataclass(frozen=True)
class WavefunctionContext:
    """A calculation-independent description of one canonical wavefunction source."""

    atoms: list[Atom]
    orbitals: list[Orbital]
    energy: float | None
    gbw_path: Path
    charge: int | None
    multiplicity: int | None
    source_type: Literal["single", "reaction-path"]
    geometry_index: int | None = None
    orbital_refs: dict[str, str] = field(default_factory=dict)

    @property
    def cache_prefix(self) -> str:
        if self.source_type == "reaction-path":
            assert self.geometry_index is not None
            return f"geometry-{self.geometry_index:03d}.{self.gbw_path.stem}"
        return f"single.{self.gbw_path.stem}"


def single_wavefunction_context(job_dir: Path) -> WavefunctionContext:
    result_path = job_dir / "result.json"
    if not result_path.is_file():
        raise FileNotFoundError(result_path)
    result = CalculationResult.model_validate_json(result_path.read_text(encoding="utf-8"))
    project = None
    project_path = job_dir / "project.json"
    if project_path.is_file():
        try:
            project = MoleculeProject.model_validate_json(
                project_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            project = None
    gbw_path = next(
        (
            candidate
            for candidate in (job_dir / "electronic.gbw", job_dir / "optimization.gbw")
            if candidate.is_file()
        ),
        None,
    )
    if gbw_path is None:
        raise FileNotFoundError("electronic.gbw or optimization.gbw")
    return WavefunctionContext(
        atoms=result.optimized_atoms,
        orbitals=result.orbitals,
        energy=result.total_energy_hartree,
        gbw_path=gbw_path.resolve(),
        charge=project.total_charge if project else None,
        multiplicity=project.multiplicity if project else None,
        source_type="single",
    )


def reaction_wavefunction_context(
    job_dir: Path,
    playback: ReactionPathPlayback,
    geometry_index: int,
) -> WavefunctionContext:
    from .reaction_path.errors import ReactionPathError

    if geometry_index < 0 or geometry_index >= len(playback.path.images):
        raise ReactionPathError("GEOMETRY_INDEX_OUT_OF_RANGE", str(geometry_index))
    image = playback.path.images[geometry_index]
    if image.convergence == "unconverged":
        raise ReactionPathError(
            "SCF_UNCONVERGED", f"geometry step {geometry_index} SCF is unconverged"
        )
    if not image.wavefunction_ref:
        raise ReactionPathError(
            "STEP_WAVEFUNCTION_MISSING",
            f"geometry step {geometry_index} has no wavefunction",
        )
    gbw_path = (job_dir / image.wavefunction_ref).resolve()
    try:
        gbw_path.relative_to(job_dir.resolve())
    except ValueError as exc:
        raise ReactionPathError("PATH_OUTSIDE_JOB", str(gbw_path)) from exc
    if not gbw_path.is_file():
        raise ReactionPathError("STEP_WAVEFUNCTION_MISSING", gbw_path.name)

    project_path = job_dir / "project.json"
    project_atoms: list[Atom] = []
    if project_path.is_file():
        try:
            project_atoms = [
                Atom.model_validate(item)
                for item in json.loads(project_path.read_text(encoding="utf-8")).get("atoms", [])
            ]
        except (OSError, ValueError, TypeError):
            project_atoms = []
    atoms: list[Atom] = []
    for index, calculated in enumerate(image.atoms):
        if index < len(project_atoms):
            atoms.append(
                project_atoms[index].model_copy(
                    update={"element": calculated.element, "position": [calculated.x, calculated.y, calculated.z]}
                )
            )
        else:
            # Imported paths may not have project.json. Stable generated IDs are
            # sufficient for axis cuts and response metadata.
            from uuid import uuid5, NAMESPACE_URL

            atoms.append(
                Atom(
                    id=uuid5(NAMESPACE_URL, f"{job_dir.name}:{geometry_index}:{index}"),
                    element=calculated.element,
                    position=[calculated.x, calculated.y, calculated.z],
                )
            )
    return WavefunctionContext(
        atoms=atoms,
        orbitals=image.orbitals,
        energy=image.energy_hartree,
        gbw_path=gbw_path,
        charge=playback.path.charge,
        multiplicity=playback.path.multiplicity,
        source_type="reaction-path",
        geometry_index=geometry_index,
        orbital_refs=image.orbital_refs,
    )
