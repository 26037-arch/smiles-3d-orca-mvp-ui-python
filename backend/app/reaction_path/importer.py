from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePath

from pydantic import ValidationError

from ..models import (
    ATOMIC_NUMBERS,
    CalculatedAtom,
    CalculatedImage,
    MoleculeProject,
    ReactionPathResult,
)
from .errors import ReactionPathError
from .geometry import align_path, normalized_path_coordinate


HARTREE_TO_KJ_MOL = 2625.499638
MAX_TRAJECTORY_BYTES = 64 * 1024 * 1024
MAX_IMAGES = 2_000
MAX_ATOMS = 10_000
_FLOAT = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
_ENERGY_PATTERNS = (
    re.compile(
        rf"(?i)(?:final\s+single\s+point\s+energy|total\s+energy|energy)"
        rf"\s*[:=]\s*(?P<value>{_FLOAT})(?:\s*(?:eh|hartree|a\.u\.))?"
    ),
    re.compile(rf"(?i)\bE\s*[:=]\s*(?P<value>{_FLOAT})(?:\s*(?:eh|hartree|a\.u\.))?"),
    re.compile(rf"(?i)coordinates\s+from\s+orca-job.*?\bE\s+(?P<value>{_FLOAT})\b"),
)


@dataclass(frozen=True)
class ParsedFrame:
    elements: list[str]
    coordinates: list[tuple[float, float, float]]
    energy_hartree: float | None


@dataclass(frozen=True)
class TrajectorySource:
    path: Path
    source_type: str


_locks_guard = threading.Lock()
_job_locks: dict[Path, threading.RLock] = {}


def _job_lock(job_dir: Path) -> threading.RLock:
    key = job_dir.resolve()
    with _locks_guard:
        return _job_locks.setdefault(key, threading.RLock())


def _safe_job_file(job_dir: Path, path: Path) -> Path:
    root = job_dir.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ReactionPathError(
            "PATH_OUTSIDE_JOB", f"Reaction-path source is outside the job directory: {path}"
        ) from exc
    if not resolved.is_file():
        raise ReactionPathError("REACTION_PATH_SOURCE_MISSING", f"Source file is missing: {path.name}")
    return resolved


def _parse_energy(comment: str) -> float | None:
    for pattern in _ENERGY_PATTERNS:
        match = pattern.search(comment)
        if match:
            try:
                value = float(match.group("value").replace("D", "E").replace("d", "e"))
            except ValueError:
                continue
            return value if math.isfinite(value) else None
    return None


def parse_multi_xyz(path: Path, *, minimum_frames: int = 2) -> list[ParsedFrame]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ReactionPathError("REACTION_PATH_SOURCE_UNREADABLE", str(exc)) from exc
    if size > MAX_TRAJECTORY_BYTES:
        raise ReactionPathError(
            "REACTION_PATH_SOURCE_TOO_LARGE",
            f"Trajectory is {size} bytes; the limit is {MAX_TRAJECTORY_BYTES} bytes.",
        )
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError as exc:
        raise ReactionPathError("REACTION_PATH_SOURCE_UNREADABLE", str(exc)) from exc

    frames: list[ParsedFrame] = []
    cursor = 0
    expected_elements: list[str] | None = None
    while cursor < len(lines):
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        if cursor >= len(lines):
            break
        count_line = cursor + 1
        try:
            atom_count = int(lines[cursor].strip())
        except ValueError as exc:
            raise ReactionPathError(
                "INVALID_XYZ_ATOM_COUNT",
                f"Image {len(frames)}, line {count_line}: expected an integer atom count.",
            ) from exc
        if atom_count < 1 or atom_count > MAX_ATOMS:
            raise ReactionPathError(
                "INVALID_XYZ_ATOM_COUNT",
                f"Image {len(frames)}, line {count_line}: atom count {atom_count} is out of range.",
            )
        cursor += 1
        if cursor >= len(lines):
            raise ReactionPathError(
                "TRUNCATED_XYZ_FRAME", f"Image {len(frames)} has no XYZ comment line."
            )
        comment = lines[cursor]
        cursor += 1
        elements: list[str] = []
        coordinates: list[tuple[float, float, float]] = []
        for atom_index in range(atom_count):
            if cursor >= len(lines):
                raise ReactionPathError(
                    "TRUNCATED_XYZ_FRAME",
                    f"Image {len(frames)} ends before atom {atom_index + 1} of {atom_count}.",
                )
            line_number = cursor + 1
            fields = lines[cursor].split()
            cursor += 1
            if len(fields) < 4:
                raise ReactionPathError(
                    "INVALID_XYZ_COORDINATE",
                    f"Image {len(frames)}, line {line_number}: expected element and x y z.",
                )
            element = fields[0][:1].upper() + fields[0][1:].lower()
            if element not in ATOMIC_NUMBERS:
                raise ReactionPathError(
                    "INVALID_XYZ_ELEMENT",
                    f"Image {len(frames)}, line {line_number}: unknown element {fields[0]!r}.",
                )
            try:
                xyz = tuple(float(value.replace("D", "E").replace("d", "e")) for value in fields[1:4])
            except ValueError as exc:
                raise ReactionPathError(
                    "INVALID_XYZ_COORDINATE",
                    f"Image {len(frames)}, line {line_number}: coordinates are not numeric.",
                ) from exc
            if not all(math.isfinite(value) for value in xyz):
                raise ReactionPathError(
                    "INVALID_XYZ_COORDINATE",
                    f"Image {len(frames)}, line {line_number}: coordinates must be finite.",
                )
            elements.append(element)
            coordinates.append(xyz)  # type: ignore[arg-type]
        if expected_elements is None:
            expected_elements = elements
        elif elements != expected_elements:
            code = "ATOM_COUNT_MISMATCH" if len(elements) != len(expected_elements) else "ELEMENT_ORDER_MISMATCH"
            raise ReactionPathError(
                code, f"Image {len(frames)} does not match the first image's atom ordering."
            )
        frames.append(ParsedFrame(elements, coordinates, _parse_energy(comment)))
        if len(frames) > MAX_IMAGES:
            raise ReactionPathError(
                "TOO_MANY_IMAGES", f"Trajectory exceeds the {MAX_IMAGES}-image limit."
            )
    if len(frames) < minimum_frames:
        raise ReactionPathError(
            "TOO_FEW_IMAGES", f"The trajectory requires at least {minimum_frames} image(s)."
        )
    return frames


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_metadata(job_dir: Path, path: Path) -> dict[str, object]:
    safe = _safe_job_file(job_dir, path)
    try:
        before = safe.stat()
        if before.st_size > MAX_TRAJECTORY_BYTES:
            raise ReactionPathError(
                "REACTION_PATH_SOURCE_TOO_LARGE",
                f"Trajectory is {before.st_size} bytes; the limit is {MAX_TRAJECTORY_BYTES} bytes.",
            )
        digest = _sha256(safe)
        after = safe.stat()
    except OSError as exc:
        raise ReactionPathError(
            "REACTION_PATH_SOURCE_UNREADABLE", f"Could not inspect {safe.name}: {exc}"
        ) from exc
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ReactionPathError(
            "REACTION_PATH_SOURCE_CHANGED", "The trajectory changed while it was being read."
        )
    return {
        "path": safe.relative_to(job_dir.resolve()).as_posix(),
        "size": after.st_size,
        "mtimeNs": after.st_mtime_ns,
        "sha256": digest,
    }


def _project_metadata(job_dir: Path) -> tuple[int | None, int | None]:
    path = job_dir / "project.json"
    try:
        project = MoleculeProject.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    return project.total_charge, project.multiplicity


class ReactionPathManifestGenerator:
    def discover(self, job_dir: Path) -> TrajectorySource:
        root = job_dir.resolve()
        try:
            files = [path for path in root.iterdir() if path.is_file()]
        except OSError as exc:
            raise ReactionPathError("REACTION_PATH_NOT_FOUND", str(exc)) from exc
        neb = sorted(
            path for path in files
            if path.name.endswith("_MEP_trj.xyz") and not path.name.endswith("_MEP_ALL_trj.xyz")
        )
        irc = sorted(path for path in files if path.name.endswith("_IRC_Full_trj.xyz"))
        candidates = [*(TrajectorySource(path, "neb") for path in neb), *(TrajectorySource(path, "irc") for path in irc)]
        if len(candidates) > 1:
            names = ", ".join(item.path.name for item in candidates)
            raise ReactionPathError(
                "AMBIGUOUS_REACTION_PATH_SOURCE", f"Multiple final trajectories were found: {names}"
            )
        if candidates:
            return candidates[0]
        if any(path.name.endswith("_MEP_ALL_trj.xyz") for path in files):
            raise ReactionPathError(
                "FINAL_NEB_TRAJECTORY_MISSING",
                "Only *_MEP_ALL_trj.xyz was found; the final *_MEP_trj.xyz is required.",
            )
        if any(
            path.name.endswith(("_IRC_F_trj.xyz", "_IRC_B_trj.xyz")) for path in files
        ):
            raise ReactionPathError(
                "FULL_IRC_TRAJECTORY_MISSING",
                "Partial IRC trajectories were found; *_IRC_Full_trj.xyz is required.",
            )
        raise ReactionPathError(
            "REACTION_PATH_NOT_FOUND", "No final ORCA NEB or IRC trajectory was found."
        )

    def ensure(self, job_dir: Path) -> Path:
        root = job_dir.resolve()
        destination = root / "reaction-path.json"
        with _job_lock(root):
            manifest_exists = destination.is_file()
            existing = self._read_existing(destination)
            if manifest_exists and existing is None:
                try:
                    return self._generate(root, self.discover(root))
                except ReactionPathError as exc:
                    if exc.code == "REACTION_PATH_NOT_FOUND":
                        raise ReactionPathError(
                            "INVALID_REACTION_PATH_MANIFEST",
                            "reaction-path.json is not valid UTF-8 JSON and no source exists to rebuild it.",
                        ) from exc
                    raise
            if existing is not None and not self._manifest_schema_valid(existing):
                try:
                    return self._generate(root, self.discover(root))
                except ReactionPathError as exc:
                    if exc.code == "REACTION_PATH_NOT_FOUND":
                        # Preserve detailed legacy-manifest validation errors in
                        # ReactionPathService when there is no source to rebuild.
                        return destination
                    raise
            metadata = existing.get("sourceMetadata") if existing else None
            if isinstance(metadata, dict) and isinstance(metadata.get("path"), str):
                source_path = self._metadata_source_path(root, metadata["path"])
                detected_type = self._source_type_from_name(source_path.name)
                current = _source_metadata(root, source_path)
                source_type = existing.get("sourceType")
                if source_type not in {"neb", "irc", "orca-optimization"}:
                    source_type = detected_type
                unchanged = all(
                    current.get(key) == metadata.get(key)
                    for key in ("path", "size", "mtimeNs", "sha256")
                )
                if unchanged and source_type == detected_type:
                    return destination
                if detected_type == "orca-optimization":
                    raise ReactionPathError(
                        "OPTIMIZATION_TRAJECTORY_INVALID",
                        "optimization trajectory가 manifest 생성 후 변경되었습니다. 계산을 다시 실행하세요.",
                    )
                return self._generate(root, TrajectorySource(source_path, detected_type))
            if existing is not None:
                return destination
            return self._generate(root, self.discover(root))

    def generate_if_available(self, job_dir: Path) -> Path | None:
        try:
            return self.ensure(job_dir)
        except ReactionPathError as exc:
            if exc.code == "REACTION_PATH_NOT_FOUND":
                return None
            raise

    @staticmethod
    def _read_existing(path: Path) -> dict[str, object] | None:
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _manifest_schema_valid(value: dict[str, object]) -> bool:
        raw = deepcopy(value)
        schema = raw.get("schemaVersion")
        if schema not in {1, 2}:
            return False
        unit = raw.pop("energyUnit", None)
        if unit not in {"hartree", "kj/mol", "eV"}:
            return False
        images = raw.get("images")
        minimum = 1 if schema == 2 else 2
        if not isinstance(images, list) or len(images) < minimum:
            return False
        for image in images:
            if not isinstance(image, dict):
                return False
            if "energy" in image:
                energy = image.pop("energy")
                if energy is None:
                    image["energyHartree"] = None
                    continue
                if not isinstance(energy, (int, float)) or isinstance(energy, bool):
                    return False
                image["energyHartree"] = (
                    energy
                    if unit == "hartree"
                    else energy / HARTREE_TO_KJ_MOL
                    if unit == "kj/mol"
                    else energy / 27.211386245988
                )
        raw["energyUnit"] = "hartree"
        try:
            ReactionPathResult.model_validate(raw)
        except ValidationError:
            return False
        return True

    @staticmethod
    def _metadata_source_path(job_dir: Path, reference: str) -> Path:
        pure = PurePath(reference)
        if pure.is_absolute() or ".." in pure.parts:
            raise ReactionPathError(
                "PATH_OUTSIDE_JOB", f"Invalid source trajectory reference: {reference}"
            )
        return _safe_job_file(job_dir, job_dir / pure)

    @staticmethod
    def _source_type_from_name(name: str) -> str:
        if name.endswith("_MEP_trj.xyz") and not name.endswith("_MEP_ALL_trj.xyz"):
            return "neb"
        if name.endswith("_IRC_Full_trj.xyz"):
            return "irc"
        if name in {"optimization_trj.xyz", "optimization.out"}:
            return "orca-optimization"
        raise ReactionPathError(
            "UNSUPPORTED_REACTION_PATH_SOURCE", f"Unsupported trajectory name: {name}"
        )

    def _generate(self, job_dir: Path, source: TrajectorySource) -> Path:
        path = _safe_job_file(job_dir, source.path)
        metadata_before = _source_metadata(job_dir, path)
        frames = parse_multi_xyz(path)
        metadata_after = _source_metadata(job_dir, path)
        if metadata_before != metadata_after:
            raise ReactionPathError(
                "REACTION_PATH_SOURCE_CHANGED", "The trajectory changed during manifest generation."
            )
        elements = frames[0].elements
        energies = [frame.energy_hartree for frame in frames]
        reference = energies[0]
        images = [
            CalculatedImage(
                id=f"image-{index}",
                index=index,
                atoms=[
                    CalculatedAtom(
                        element=element, atomIndex=atom_index, x=xyz[0], y=xyz[1], z=xyz[2]
                    )
                    for atom_index, (element, xyz) in enumerate(
                        zip(frame.elements, frame.coordinates, strict=True)
                    )
                ],
                energyHartree=frame.energy_hartree,
                relativeEnergyKjMol=(
                    None
                    if reference is None or frame.energy_hartree is None
                    else (frame.energy_hartree - reference) * HARTREE_TO_KJ_MOL
                ),
            )
            for index, frame in enumerate(frames)
        ]
        aligned = align_path(images, elements)
        coordinates = normalized_path_coordinate(images, aligned)
        images = [
            image.model_copy(update={"reaction_coordinate": float(coordinates[index])})
            for index, image in enumerate(images)
        ]
        charge, multiplicity = _project_metadata(job_dir)
        result = ReactionPathResult(
            schemaVersion=1,
            sourceType=source.source_type,
            atomCount=len(elements),
            elements=elements,
            charge=charge,
            multiplicity=multiplicity,
            images=images,
            hasPhysicalTime=False,
            energyUnit="hartree",
            relativeEnergyUnit="kJ/mol",
            energyReference="first-image",
            reactionCoordinateSource="derived-aligned-cartesian",
            sourceTrajectory=metadata_after["path"],
            sourceMetadata=metadata_after,
        )
        destination = job_dir / "reaction-path.json"
        self._atomic_write(destination, result.model_dump(mode="json", by_alias=True))
        return destination

    @staticmethod
    def _atomic_write(destination: Path, data: dict[str, object]) -> None:
        temporary = destination.with_name(f"{destination.name}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            # Validate the complete temporary document before replacing a prior manifest.
            parsed = json.loads(temporary.read_text(encoding="utf-8"))
            ReactionPathResult.model_validate(parsed)
            os.replace(temporary, destination)
        except (OSError, ValueError, ValidationError) as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            if isinstance(exc, ReactionPathError):
                raise
            raise ReactionPathError(
                "REACTION_PATH_WRITE_FAILED", f"Could not save reaction-path.json: {exc}"
            ) from exc
