from __future__ import annotations

import json
import hashlib
import threading
from copy import deepcopy
from pathlib import Path, PurePath
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import ValidationError

from ..cache import BoundedLRU, DerivedCacheManager
from ..fields import CubeFieldService
from ..models import (
    OrbitalMatch,
    PlotField,
    ReactionPathPlayback,
    ReactionPathResult,
    SurfaceRequest,
)
from ..surfaces.cube import read_cube
from ..surfaces.mesh import contour_to_ply
from ..wavefunction import WavefunctionContext, reaction_wavefunction_context
from .geometry import create_display_frames, image_coordinates, mass_weighted_kabsch_transform
from .errors import ReactionPathError
from .importer import ReactionPathManifestGenerator
from .orbitals import (
    GridOrbitalOverlapProvider,
    OrbitalTracker,
    interpolate_scalar_fields,
    transformed_common_grid,
    trilinear_resample_transformed,
)

if TYPE_CHECKING:
    from ..surfaces.service import SurfaceService


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
    TRACKING_VERSION = "signed-overlap-v2"

    def __init__(
        self,
        jobs,
        fields: CubeFieldService | None = None,
        surfaces: SurfaceService | None = None,
        cache: DerivedCacheManager | None = None,
    ):
        self.jobs = jobs
        self.fields = fields
        self.surfaces = surfaces
        self.cache = cache or getattr(jobs, "derived_cache", None)
        self.generator = ReactionPathManifestGenerator()
        self._cache: dict[tuple[UUID, int], ReactionPathPlayback] = {}
        settings = getattr(jobs, "settings", None)
        self._cube_cache = BoundedLRU(
            64,
            max_bytes=getattr(settings, "max_ram_cube_cache_bytes", 256_000_000),
            size_of=lambda cube: int(
                cube.values.nbytes + cube.origin.nbytes + cube.axes.nbytes
            ),
        )
        self._overlap_cache = BoundedLRU(
            getattr(settings, "max_ram_overlap_entries", 512)
        )
        self._tracking_lock = threading.RLock()

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

    def track_orbital(
        self, job_id: UUID, orbital_id: str, source_geometry_index: int = 0
    ) -> dict[str, object]:
        # Tracking is metadata-only. Frame meshes are requested separately and
        # generated lazily by tracking_frame_surface().
        return self._track_metadata(job_id, orbital_id, source_geometry_index)

    def wavefunction_context(
        self, job_id: UUID, geometry_index: int
    ) -> WavefunctionContext:
        job_dir = self.jobs._job_dir(job_id)
        return reaction_wavefunction_context(job_dir, self.load(job_id), geometry_index)

    def create_geometry_surface(
        self, job_id: UUID, geometry_index: int, request: SurfaceRequest
    ):
        if self.surfaces is None:
            raise RuntimeError("surface service is unavailable")
        return self.surfaces.create_for_context(
            job_id, request, self.wavefunction_context(job_id, geometry_index)
        )

    def _track_metadata(
        self, job_id: UUID, orbital_id: str, source_geometry_index: int
    ) -> dict[str, object]:
        playback = self.load(job_id)
        job_dir = self.jobs._job_dir(job_id)
        try:
            spin, index_text = orbital_id.rsplit(":", 1)
            int(index_text)
        except (ValueError, TypeError) as exc:
            raise ReactionPathError("INVALID_ORBITAL_ID", orbital_id) from exc
        if source_geometry_index < 0 or source_geometry_index >= len(playback.path.images):
            raise ReactionPathError(
                "GEOMETRY_INDEX_OUT_OF_RANGE", str(source_geometry_index)
            )
        source_image = playback.path.images[source_geometry_index]
        if source_image.convergence == "unconverged":
            raise ReactionPathError(
                "SCF_UNCONVERGED", "source geometry SCF is unconverged"
            )
        available = {item.internal_id for item in source_image.orbitals} | set(
            source_image.orbital_refs
        )
        if available and orbital_id not in available:
            raise ReactionPathError("INVALID_ORBITAL_ID", orbital_id)

        signature = [self.TRACKING_VERSION, str(source_geometry_index), orbital_id]
        for image in playback.path.images:
            if image.wavefunction_ref:
                path = job_dir / image.wavefunction_ref
                signature.append(
                    f"{image.index}:{path.stat().st_mtime_ns if path.is_file() else 0}"
                )
        tracking_id = hashlib.sha256(":".join(signature).encode()).hexdigest()[:32]
        directory = self._tracking_directory(job_dir)
        metadata_path = directory / f"{tracking_id}.json"
        with self._tracking_lock:
            if metadata_path.is_file():
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                payload["cacheHit"] = True
                if self.cache is not None:
                    self.cache.record(metadata_path)
                return payload

            source_path = self._ensure_context_orbital_cube(
                job_dir, playback, source_geometry_index, orbital_id
            )
            tracked: dict[int, tuple[str, Path, int]] = {
                source_geometry_index: (orbital_id, source_path, 1)
            }
            transitions: list[dict[str, object]] = []
            for direction in (-1, 1):
                branch, branch_transitions = self._track_branch(
                    job_dir,
                    playback,
                    source_geometry_index,
                    orbital_id,
                    spin,
                    direction,
                )
                tracked.update(branch)
                transitions.extend(branch_transitions)
            payload: dict[str, object] = {
                "trackingId": tracking_id,
                "sourceOrbital": orbital_id,
                "sourceGeometryIndex": source_geometry_index,
                "threshold": 0.6,
                "active": len(tracked) == len(playback.path.images),
                "steps": [
                    {"geometry": index, "orbital": item[0], "phase": item[2]}
                    for index, item in sorted(tracked.items())
                ],
                "transitions": sorted(
                    transitions,
                    key=lambda item: (
                        min(item["leftImageIndex"], item["rightImageIndex"]),
                        item["leftImageIndex"],
                    ),
                ),
                "cacheHit": False,
            }
            temporary = metadata_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            temporary.replace(metadata_path)
            if self.cache is not None:
                self.cache.record(metadata_path)
            return payload

    def _track_branch(
        self,
        job_dir: Path,
        playback: ReactionPathPlayback,
        source_index: int,
        source_orbital: str,
        spin: str,
        direction: int,
    ) -> tuple[dict[int, tuple[str, Path, int]], list[dict[str, object]]]:
        tracked: dict[int, tuple[str, Path, int]] = {}
        transitions: list[dict[str, object]] = []
        current_index = source_index
        current_orbital = source_orbital
        current_path = self._ensure_context_orbital_cube(
            job_dir, playback, current_index, current_orbital
        )
        phase_sign = 1
        while 0 <= current_index + direction < len(playback.path.images):
            next_index = current_index + direction
            current_image = playback.path.images[current_index]
            next_image = playback.path.images[next_index]
            candidates: list[tuple[str, Path]] = []
            if next_image.convergence != "unconverged":
                current_number = int(current_orbital.rsplit(":", 1)[1])
                candidate_ids = (
                    [item.internal_id for item in next_image.orbitals]
                    if next_image.orbitals
                    else list(next_image.orbital_refs)
                )
                for candidate_id in candidate_ids:
                    try:
                        candidate_spin, candidate_number = candidate_id.rsplit(":", 1)
                        if (
                            candidate_spin == spin
                            and abs(int(candidate_number) - current_number) <= 5
                        ):
                            candidates.append(
                                (
                                    candidate_id,
                                    self._ensure_context_orbital_cube(
                                        job_dir, playback, next_index, candidate_id
                                    ),
                                )
                            )
                    except (ValueError, ReactionPathError):
                        continue
            tracker = OrbitalTracker(current_orbital)
            signed = 0.0
            if candidates:
                overlaps = [
                    (
                        candidate_id,
                        self._signed_overlap(
                            current_path,
                            candidate_path,
                            current_image,
                            next_image,
                            playback.path.elements,
                        ),
                    )
                    for candidate_id, candidate_path in candidates
                ]
                candidate_id, signed = max(overlaps, key=lambda item: abs(item[1]))
                match = tracker.advance(candidate_id, signed)
                ranked = sorted((abs(value) for _, value in overlaps), reverse=True)
                if (
                    match.status == "matched"
                    and len(ranked) > 1
                    and ranked[0] - ranked[1] < 0.05
                ):
                    match = OrbitalMatch(
                        leftOrbitalId=match.left_orbital_id,
                        rightOrbitalId=match.right_orbital_id,
                        signedOverlap=match.signed_overlap,
                        absoluteOverlap=match.absolute_overlap,
                        status="ambiguous",
                    )
            else:
                match = tracker.advance(current_orbital, 0.0)
            if match.status in {"matched", "ambiguous"} and signed < 0:
                phase_sign *= -1
            transitions.append(
                {
                    "leftImageIndex": current_index,
                    "rightImageIndex": next_index,
                    "match": match.model_dump(mode="json", by_alias=True),
                    "phaseSign": phase_sign,
                }
            )
            if match.right_orbital_id is None:
                break
            current_orbital = match.right_orbital_id
            current_path = next(
                path for candidate, path in candidates if candidate == current_orbital
            )
            tracked[next_index] = (current_orbital, current_path, phase_sign)
            current_index = next_index
        return tracked, transitions

    def tracking_frame_surface(
        self,
        job_id: UUID,
        tracking_id: str,
        frame_index: int,
        isovalue: float = 0.03,
    ) -> dict[str, object]:
        playback = self.load(job_id)
        if frame_index < 0 or frame_index >= len(playback.display_frames):
            raise ReactionPathError("FRAME_INDEX_OUT_OF_RANGE", str(frame_index))
        job_dir = self.jobs._job_dir(job_id)
        metadata = self._tracking_metadata(job_dir, tracking_id)
        tracked = {item["geometry"]: item for item in metadata["steps"]}
        frame = playback.display_frames[frame_index]
        if (
            frame.left_image_index not in tracked
            or frame.right_image_index not in tracked
        ):
            raise ReactionPathError(
                "TRACKING_NOT_AVAILABLE_FOR_FRAME", str(frame_index)
            )
        left_info = tracked[frame.left_image_index]
        right_info = tracked[frame.right_image_index]
        left_path = self._ensure_context_orbital_cube(
            job_dir, playback, frame.left_image_index, left_info["orbital"]
        )
        right_path = self._ensure_context_orbital_cube(
            job_dir, playback, frame.right_image_index, right_info["orbital"]
        )
        cubes = [self._load_cube(left_path), self._load_cube(right_path)]
        reference = image_coordinates(playback.path.images[0])
        transforms = [
            mass_weighted_kabsch_transform(
                reference,
                image_coordinates(playback.path.images[index]),
                playback.path.elements,
            )
            for index in (frame.left_image_index, frame.right_image_index)
        ]
        grid = transformed_common_grid(cubes, transforms)
        left = trilinear_resample_transformed(cubes[0], grid, transforms[0]) * left_info[
            "phase"
        ]
        right = trilinear_resample_transformed(cubes[1], grid, transforms[1]) * right_info[
            "phase"
        ]
        values = interpolate_scalar_fields(left, right, frame.interpolation_value)
        frame_cube = grid.__class__(grid.origin, grid.axes, grid.shape, values)
        directory = self._tracking_directory(job_dir)
        urls: dict[str, str] = {}
        outputs: list[Path] = []
        all_hit = True
        for phase, level in (("positive", isovalue), ("negative", -isovalue)):
            if phase == "positive" and float(values.max()) < level:
                continue
            if phase == "negative" and float(values.min()) > level:
                continue
            key = hashlib.sha256(
                f"{tracking_id}:{frame_index}:{isovalue:.9g}:{phase}".encode()
            ).hexdigest()[:32]
            output = directory / f"{key}.ply"
            outputs.append(output)
            if not output.is_file():
                all_hit = False
                contour_to_ply(frame_cube, level, output)
            urls[phase] = (
                f"/api/jobs/{job_id}/reaction-path/surfaces/{key}/mesh"
            )
        if not urls:
            raise ReactionPathError("EMPTY_TRACKING_SURFACE", str(isovalue))
        if self.cache is not None:
            for output in outputs:
                self.cache.record(output, protected=outputs)
        return {"frameIndex": frame_index, "meshUrls": urls, "cacheHit": all_hit}

    def _tracking_metadata(self, job_dir: Path, tracking_id: str) -> dict[str, object]:
        if len(tracking_id) != 32 or any(
            character not in "0123456789abcdef" for character in tracking_id
        ):
            raise ReactionPathError("INVALID_TRACKING_ID", tracking_id)
        path = self._tracking_directory(job_dir) / f"{tracking_id}.json"
        if not path.is_file():
            raise ReactionPathError("TRACKING_NOT_FOUND", tracking_id)
        if self.cache is not None:
            self.cache.record(path)
        return json.loads(path.read_text(encoding="utf-8"))

    def _tracking_directory(self, job_dir: Path) -> Path:
        if self.cache is not None:
            return self.cache.directory(job_dir, "tracking")
        directory = job_dir / "reaction-surfaces"
        directory.mkdir(exist_ok=True)
        return directory

    def _ensure_context_orbital_cube(
        self,
        job_dir: Path,
        playback: ReactionPathPlayback,
        geometry_index: int,
        orbital_id: str,
    ) -> Path:
        image = playback.path.images[geometry_index]
        if self.fields is None:
            return self._ensure_orbital_cube(job_dir, image, orbital_id)
        context = reaction_wavefunction_context(job_dir, playback, geometry_index)
        try:
            spin, index_text = orbital_id.rsplit(":", 1)
            orbital_index = int(index_text)
        except ValueError as exc:
            raise ReactionPathError("INVALID_ORBITAL_ID", orbital_id) from exc
        try:
            path, _ = self.fields.ensure_context(
                job_dir,
                context,
                PlotField(
                    field="mo",
                    orbital_internal_id=orbital_id,
                    orbital_index=orbital_index,
                    spin=spin,
                ),
                resolution=40,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise ReactionPathError(
                "ORBITAL_TRACKING_FAILED",
                f"geometry step {geometry_index} {orbital_id} Cube generation failed: {exc}",
            ) from exc
        return path

    def mesh_path(self, job_id: UUID, surface_id: str) -> Path:
        if len(surface_id) != 32 or any(character not in "0123456789abcdef" for character in surface_id):
            raise FileNotFoundError(surface_id)
        job_dir = self.jobs._job_dir(job_id)
        for directory in (job_dir / "cache" / "tracking", job_dir / "reaction-surfaces"):
            expected = directory.resolve()
            path = (directory / f"{surface_id}.ply").resolve()
            if path.parent == expected and path.is_file():
                if self.cache is not None and directory.name == "tracking":
                    self.cache.record(path)
                return path
        raise FileNotFoundError(surface_id)

    def _load_cube(self, path: Path):
        key = (path, path.stat().st_mtime_ns)
        if key not in self._cube_cache:
            self._cube_cache[key] = read_cube(path)
        return self._cube_cache[key]

    @staticmethod
    def _ensure_orbital_cube(job_dir: Path, image, orbital_id: str) -> Path:
        if reference := image.orbital_refs.get(orbital_id):
            path = job_dir / reference
            if path.is_file():
                return path
        if not image.wavefunction_ref:
            raise ReactionPathError(
                "STEP_WAVEFUNCTION_MISSING",
                f"geometry step {image.index}의 wavefunction이 없습니다",
            )
        try:
            spin, index_text = orbital_id.rsplit(":", 1)
            orbital_index = int(index_text)
        except ValueError as exc:
            raise ReactionPathError("INVALID_ORBITAL_ID", orbital_id) from exc
        gbw = (job_dir / image.wavefunction_ref).resolve()
        try:
            gbw.relative_to(job_dir.resolve())
        except ValueError as exc:
            raise ReactionPathError("PATH_OUTSIDE_JOB", str(gbw)) from exc
        if not gbw.is_file():
            raise ReactionPathError("STEP_WAVEFUNCTION_MISSING", gbw.name)
        cube_path = job_dir / f"{gbw.stem}.mo.{spin}.{orbital_index}.cube"
        if cube_path.is_file():
            return cube_path
        try:
            from opi.output.core import Output

            output = Output(gbw.stem, working_dir=job_dir, version_check=False, parse=False)
            output.collect_gbw_json_files()
            cube_output = output.plot_mo(
                orbital_index,
                operator=1 if spin == "beta" else 0,
                resolution=40,
                gbw_type="gbw",
                timeout=600,
            )
            cube = getattr(cube_output, "cube", None)
            if not cube:
                raise RuntimeError("orca_plot returned no cube")
            cube_path.write_text(cube, encoding="utf-8")
        except Exception as exc:
            raise ReactionPathError(
                "ORBITAL_TRACKING_FAILED",
                f"geometry step {image.index}의 {orbital_id} cube 생성 실패: {exc}",
            ) from exc
        return cube_path

    def _signed_overlap(
        self, left_path: Path, right_path: Path, left_image, right_image, elements: list[str]
    ) -> float:
        key = (left_path, left_path.stat().st_mtime_ns, right_path, right_path.stat().st_mtime_ns)
        if key in self._overlap_cache:
            return self._overlap_cache[key]
        left = self._load_cube(left_path)
        right = self._load_cube(right_path)
        reference = image_coordinates(left_image)
        transforms = [
            mass_weighted_kabsch_transform(reference, reference, elements),
            mass_weighted_kabsch_transform(
                reference, image_coordinates(right_image), elements
            ),
        ]
        grid = transformed_common_grid([left, right], transforms)
        left_on_grid = grid.__class__(
            grid.origin,
            grid.axes,
            grid.shape,
            trilinear_resample_transformed(left, grid, transforms[0]),
        )
        right_on_grid = grid.__class__(
            grid.origin,
            grid.axes,
            grid.shape,
            trilinear_resample_transformed(right, grid, transforms[1]),
        )
        overlap = GridOrbitalOverlapProvider().compute_signed_overlap(left_on_grid, right_on_grid)
        self._overlap_cache[key] = overlap
        return overlap

    def _parse(self, job_dir: Path, raw: dict) -> ReactionPathPlayback:
        raw = deepcopy(raw)
        unit = raw.pop("energyUnit", None)
        if unit not in {"hartree", "kj/mol", "eV"}:
            raise ReactionPathError("ENERGY_UNIT_REQUIRED", "energyUnit는 hartree, kj/mol 또는 eV여야 합니다")
        raw_images = raw.get("images")
        minimum = 1 if raw.get("schemaVersion") == 2 else 2
        if not isinstance(raw_images, list) or len(raw_images) < minimum:
            raise ReactionPathError("TOO_FEW_IMAGES", f"경로에는 계산 지점이 {minimum}개 이상 필요합니다")
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
        frames = create_display_frames(
            result.images,
            result.elements,
            interpolate_energy=result.schema_version == 1,
        )
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
