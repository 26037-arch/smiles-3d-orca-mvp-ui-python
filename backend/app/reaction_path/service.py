from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from pathlib import Path, PurePath
from uuid import UUID

from pydantic import ValidationError

from ..models import ReactionPathPlayback, ReactionPathResult
from ..surfaces.cube import read_cube
from ..surfaces.mesh import contour_to_ply
from .geometry import create_display_frames, image_coordinates, mass_weighted_kabsch_transform
from .errors import ReactionPathError
from .importer import ReactionPathManifestGenerator
from .orbitals import (
    GridOrbitalOverlapProvider,
    OrbitalTracker,
    common_grid,
    interpolate_scalar_fields,
    transformed_common_grid,
    trilinear_resample,
    trilinear_resample_transformed,
)


HARTREE_TO_KJ_MOL = 2625.499638
EV_TO_HARTREE = 1 / 27.211386245988


def _contained_reference(job_dir: Path, reference: str, *, require_exists: bool = False) -> str:
    path = PurePath(reference)
    if path.is_absolute() or ".." in path.parts:
        raise ReactionPathError("PATH_OUTSIDE_JOB", f"작업 디렉터리 밖의 파일 참조입니다: {reference}")
    resolved = (job_dir / path).resolve()
    try:
        resolved.relative_to(job_dir.resolve())
    except ValueError as exc:
        raise ReactionPathError("PATH_OUTSIDE_JOB", f"작업 디렉터리 밖의 파일 참조입니다: {reference}") from exc
    if require_exists and not resolved.is_file():
        raise ReactionPathError("REFERENCED_FILE_MISSING", f"참조 파일을 찾을 수 없습니다: {reference}")
    return str(path).replace("\\", "/")


class ReactionPathService:
    def __init__(self, jobs):
        self.jobs = jobs
        self.generator = ReactionPathManifestGenerator()
        self._cache: dict[tuple[UUID, int], ReactionPathPlayback] = {}
        self._cube_cache: dict[tuple[Path, int], object] = {}
        self._overlap_cache: dict[tuple[Path, int, Path, int], float] = {}

    def load(self, job_id: UUID) -> ReactionPathPlayback:
        job_dir = self.jobs._job_dir(job_id)
        manifest = self.generator.ensure(job_dir)
        key = (job_id, manifest.stat().st_mtime_ns)
        if key in self._cache:
            return self._cache[key]
        try:
            raw = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReactionPathError("INVALID_REACTION_PATH_MANIFEST", f"reaction-path.json 파싱 실패: {exc}") from exc
        playback = self._parse(job_dir, raw)
        self._cache = {cache_key: value for cache_key, value in self._cache.items() if cache_key[0] != job_id}
        self._cache[key] = playback
        return playback

    def track_orbital(self, job_id: UUID, orbital_id: str, isovalue: float = 0.03) -> dict[str, object]:
        playback = self.load(job_id)
        job_dir = self.jobs._job_dir(job_id)
        try:
            spin, index_text = orbital_id.rsplit(":", 1)
            orbital_index = int(index_text)
        except (ValueError, TypeError) as exc:
            raise ReactionPathError("INVALID_ORBITAL_ID", f"오비탈 ID 형식이 잘못되었습니다: {orbital_id}") from exc
        tracker = OrbitalTracker(orbital_id)
        phase_sign = 1
        steps: list[dict[str, object]] = []
        tracked: list[tuple[str, Path, int]] = []
        first_ref = playback.path.images[0].orbital_refs.get(orbital_id)
        if not first_ref:
            raise ReactionPathError("ORBITAL_CUBE_MISSING", f"계산 지점 1에 {orbital_id} cube가 없습니다")
        if playback.path.images[0].convergence == "unconverged":
            raise ReactionPathError("SCF_UNCONVERGED", "계산 지점 1의 SCF가 수렴하지 않아 MO를 추적할 수 없습니다")
        if not (job_dir / first_ref).is_file():
            raise ReactionPathError("ORBITAL_CUBE_MISSING", f"계산 지점 1의 cube 파일이 없습니다: {first_ref}")
        tracked.append((orbital_id, job_dir / first_ref, phase_sign))
        for image_index in range(len(playback.path.images) - 1):
            left_image = playback.path.images[image_index]
            right_image = playback.path.images[image_index + 1]
            left_ref = left_image.orbital_refs.get(tracker.current_orbital_id)
            if not left_ref:
                raise ReactionPathError("ORBITAL_CUBE_MISSING", f"계산 지점 {image_index + 1}에 {tracker.current_orbital_id} cube가 없습니다")
            candidates: list[tuple[str, str]] = []
            if right_image.convergence == "unconverged":
                match = tracker.advance(tracker.current_orbital_id, 0.0)
                steps.append({
                    "leftImageIndex": image_index, "rightImageIndex": image_index + 1,
                    "match": match.model_dump(mode="json", by_alias=True), "phaseSign": phase_sign,
                })
                break
            for candidate_id, reference in right_image.orbital_refs.items():
                try:
                    candidate_spin, candidate_index = candidate_id.rsplit(":", 1)
                    if candidate_spin == spin and abs(int(candidate_index) - orbital_index) <= 5:
                        if (job_dir / reference).is_file():
                            candidates.append((candidate_id, reference))
                except ValueError:
                    continue
            if not candidates:
                match = tracker.advance(tracker.current_orbital_id, 0.0)
            else:
                left_path = job_dir / left_ref
                overlaps = [(candidate_id, self._signed_overlap(left_path, job_dir / reference)) for candidate_id, reference in candidates]
                candidate_id, signed = max(overlaps, key=lambda item: abs(item[1]))
                match = tracker.advance(candidate_id, signed)
                if match.status == "matched" and signed < 0:
                    phase_sign *= -1
            steps.append({
                "leftImageIndex": image_index,
                "rightImageIndex": image_index + 1,
                "match": match.model_dump(mode="json", by_alias=True),
                "phaseSign": phase_sign,
            })
            if not tracker.active:
                break
            assert match.right_orbital_id is not None
            next_ref = right_image.orbital_refs[match.right_orbital_id]
            tracked.append((match.right_orbital_id, job_dir / next_ref, phase_sign))
        frame_surfaces = self._prepare_orbital_frames(job_dir, playback, tracked, orbital_id, isovalue)
        return {
            "orbitalId": orbital_id, "threshold": tracker.threshold, "active": tracker.active,
            "steps": steps, "frameSurfaces": frame_surfaces,
        }

    def _prepare_orbital_frames(
        self, job_dir: Path, playback: ReactionPathPlayback,
        tracked: list[tuple[str, Path, int]], orbital_id: str, isovalue: float,
    ) -> dict[str, dict[str, str]]:
        if not tracked:
            return {}
        cubes = [self._load_cube(path) for _, path, _ in tracked]
        reference = image_coordinates(playback.path.images[0])
        transforms = [
            mass_weighted_kabsch_transform(
                reference, image_coordinates(playback.path.images[index]), playback.path.elements
            )
            for index in range(len(tracked))
        ]
        grid = transformed_common_grid(cubes, transforms)
        fields = [
            trilinear_resample_transformed(cube, grid, transform) * sign
            for cube, transform, (_, _, sign) in zip(cubes, transforms, tracked, strict=True)
        ]
        directory = job_dir / "reaction-surfaces"
        directory.mkdir(exist_ok=True)
        result: dict[str, dict[str, str]] = {}
        maximum_image = len(tracked) - 1
        digest_seed = ":".join(
            [orbital_id, f"{isovalue:.9g}", *[f"{path}:{path.stat().st_mtime_ns}:{sign}" for _, path, sign in tracked]]
        )
        for frame in playback.display_frames:
            if frame.left_image_index > maximum_image or frame.right_image_index > maximum_image:
                continue
            left = fields[frame.left_image_index]
            right = fields[frame.right_image_index]
            values = interpolate_scalar_fields(left, right, frame.interpolation_value)
            frame_cube = grid.__class__(grid.origin, grid.axes, grid.shape, values)
            urls: dict[str, str] = {}
            for phase, level in (("positive", isovalue), ("negative", -isovalue)):
                if phase == "positive" and float(values.max()) < level:
                    continue
                if phase == "negative" and float(values.min()) > level:
                    continue
                key = hashlib.sha256(f"{digest_seed}:{frame.index}:{phase}".encode()).hexdigest()[:32]
                output = directory / f"{key}.ply"
                if not output.is_file():
                    contour_to_ply(frame_cube, level, output)
                urls[phase] = f"/api/jobs/{job_dir.name}/reaction-path/surfaces/{key}/mesh"
            if urls:
                result[str(frame.index)] = urls
        return result

    def mesh_path(self, job_id: UUID, surface_id: str) -> Path:
        if len(surface_id) != 32 or any(character not in "0123456789abcdef" for character in surface_id):
            raise FileNotFoundError(surface_id)
        directory = (self.jobs._job_dir(job_id) / "reaction-surfaces").resolve()
        path = (directory / f"{surface_id}.ply").resolve()
        if path.parent != directory or not path.is_file():
            raise FileNotFoundError(surface_id)
        return path

    def _load_cube(self, path: Path):
        key = (path, path.stat().st_mtime_ns)
        if key not in self._cube_cache:
            self._cube_cache[key] = read_cube(path)
        return self._cube_cache[key]

    def _signed_overlap(self, left_path: Path, right_path: Path) -> float:
        key = (left_path, left_path.stat().st_mtime_ns, right_path, right_path.stat().st_mtime_ns)
        if key in self._overlap_cache:
            return self._overlap_cache[key]
        left = self._load_cube(left_path)
        right = self._load_cube(right_path)
        grid = common_grid([left, right])
        left_on_grid = grid.__class__(grid.origin, grid.axes, grid.shape, trilinear_resample(left, grid))
        right_on_grid = grid.__class__(grid.origin, grid.axes, grid.shape, trilinear_resample(right, grid))
        overlap = GridOrbitalOverlapProvider().compute_signed_overlap(left_on_grid, right_on_grid)
        self._overlap_cache[key] = overlap
        return overlap

    def _parse(self, job_dir: Path, raw: dict) -> ReactionPathPlayback:
        raw = deepcopy(raw)
        unit = raw.pop("energyUnit", None)
        if unit not in {"hartree", "kj/mol", "eV"}:
            raise ReactionPathError("ENERGY_UNIT_REQUIRED", "energyUnit는 hartree, kj/mol 또는 eV여야 합니다")
        raw_images = raw.get("images")
        if not isinstance(raw_images, list) or len(raw_images) < 2:
            raise ReactionPathError("TOO_FEW_IMAGES", "반응 경로에는 계산 지점이 두 개 이상 필요합니다")
        energies: list[float | None] = []
        for item in raw_images:
            if not isinstance(item, dict):
                raise ReactionPathError(
                    "INVALID_REACTION_PATH_MANIFEST", "Each reaction-path image must be an object."
                )
            if "energy" in item:
                value = item.pop("energy")
                if value is None:
                    hartree = None
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    hartree = value if unit == "hartree" else value / HARTREE_TO_KJ_MOL if unit == "kj/mol" else value * EV_TO_HARTREE
                else:
                    raise ReactionPathError(
                        "INVALID_REACTION_PATH_MANIFEST", "Image energy must be numeric or null."
                    )
                item["energyHartree"] = hartree
            energy = item.get("energyHartree")
            if energy is not None and (
                not isinstance(energy, (int, float)) or isinstance(energy, bool)
            ):
                raise ReactionPathError(
                    "INVALID_REACTION_PATH_MANIFEST", "energyHartree must be numeric or null."
                )
            energies.append(energy)
        if energies and energies[0] is not None:
            reference = energies[0]
            for item in raw_images:
                item["relativeEnergyKjMol"] = (
                    None
                    if item.get("energyHartree") is None
                    else (
                        item["energyHartree"] - reference
                    ) * HARTREE_TO_KJ_MOL
                )
        else:
            for item in raw_images:
                item["relativeEnergyKjMol"] = None
        raw["energyUnit"] = "hartree"
        try:
            result = ReactionPathResult.model_validate(raw)
        except ValidationError as exc:
            raise ReactionPathError("INVALID_REACTION_PATH_MANIFEST", str(exc)) from exc
        self._validate_images(job_dir, result)
        frames = create_display_frames(result.images, result.elements)
        return ReactionPathPlayback(path=result, displayFrames=frames)

    @staticmethod
    def _validate_images(job_dir: Path, result: ReactionPathResult) -> None:
        if len(result.elements) != result.atom_count:
            raise ReactionPathError("ATOM_COUNT_MISMATCH", "elements와 atomCount가 일치하지 않습니다")
        if result.source_trajectory:
            _contained_reference(job_dir, result.source_trajectory, require_exists=True)
        if result.source_metadata:
            metadata_path = _contained_reference(
                job_dir, result.source_metadata.path, require_exists=True
            )
            if result.source_trajectory and metadata_path != result.source_trajectory:
                raise ReactionPathError(
                    "REACTION_PATH_SOURCE_MISMATCH",
                    "sourceTrajectory and sourceMetadata.path must refer to the same file.",
                )
        if [image.index for image in result.images] != list(range(len(result.images))):
            raise ReactionPathError("IMAGE_INDEX_MISMATCH", "계산 지점 index는 0부터 연속이어야 합니다")
        for image in result.images:
            if len(image.atoms) != result.atom_count:
                raise ReactionPathError("ATOM_COUNT_MISMATCH", f"계산 지점 {image.index}의 원자 수가 다릅니다")
            if [atom.atom_index for atom in image.atoms] != list(range(result.atom_count)):
                raise ReactionPathError("ATOM_ORDER_MISMATCH", f"계산 지점 {image.index}의 atomIndex 순서가 다릅니다")
            if [atom.element for atom in image.atoms] != result.elements:
                raise ReactionPathError("ELEMENT_ORDER_MISMATCH", f"계산 지점 {image.index}의 원소 또는 원자 순서가 다릅니다")
            if image.wavefunction_ref:
                _contained_reference(job_dir, image.wavefunction_ref, require_exists=True)
            for reference in image.orbital_refs.values():
                _contained_reference(job_dir, reference, require_exists=True)
