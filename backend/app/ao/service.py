from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from ..chemistry.diagnostics import orca_tool
from ..chemistry.opi_adapter import ChemistryError
from ..config import LocalSettings
from ..jobs.manager import JobManager
from ..models import (
    BasisSurfaceRequest,
    JobMode,
    OrbitalComposition,
    SurfaceRecord,
)
from ..surfaces.cube import CubeData, read_cube
from ..surfaces.mesh import contour_to_ply
from .analysis import (
    ANALYSIS_VERSION,
    INTERPRETATION_VERSION,
    contribution_models,
    parse_orca_gbw_json,
)


JSON_CONFIG = {
    "MOCoefficients": True,
    "Basisset": True,
    "1elIntegrals": ["S"],
    "JSONFormats": ["json"],
}
AO_MESH_VERSION = "ao-component-mesh-v1"


class AOAnalysisService:
    def __init__(
        self,
        jobs: JobManager,
        settings: LocalSettings,
        *,
        extractor: Callable[[Path, Path], dict] | None = None,
        cube_generator: Callable[[Path, Path, int, Path], None] | None = None,
    ) -> None:
        self.jobs = jobs
        self.settings = settings
        self.extractor = extractor or self._extract_json
        self.cube_generator = cube_generator or self._generate_ao_cube
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def composition(
        self, job_id: UUID, spin: str, orca_index: int, *, offset: int, limit: int
    ) -> OrbitalComposition:
        if spin not in {"restricted", "alpha", "beta"}:
            raise ChemistryError("AO_SPIN_INDEX_MISMATCH", f"Unsupported spin channel: {spin}.")
        record = self.jobs.get(job_id)
        result = self.jobs.result(job_id)
        if record.mode == JobMode.DEMO or result.demo:
            raise ChemistryError(
                "AO_DEMO_UNAVAILABLE",
                "AO composition is available only for a real ORCA calculation.",
            )
        orbital = next(
            (
                item
                for item in result.orbitals
                if item.spin == spin and item.orca_index == orca_index
            ),
            None,
        )
        if orbital is None:
            raise ChemistryError("AO_MO_INDEX_MISMATCH", "The requested MO is not in this job result.")

        job_dir = self.jobs._job_dir(job_id)
        gbw = self._final_gbw(job_dir)
        gbw_hash = _sha256(gbw)
        key = self._analysis_key(gbw_hash, spin, orca_index)
        cache_dir = job_dir / "ao-analysis"
        cache_dir.mkdir(exist_ok=True)
        cache_path = cache_dir / f"{key}.json"
        lock = self._lock(str(cache_path.resolve()))
        with lock:
            cache_hit = cache_path.is_file()
            if cache_hit:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
            else:
                document = self.extractor(job_dir, gbw)
                parsed = parse_orca_gbw_json(document, spin, orca_index)  # type: ignore[arg-type]
                items, groups = contribution_models(parsed)
                payload = {
                    "cache_key": {
                        "gbw_sha256": gbw_hash,
                        "spin": spin,
                        "orca_index": orca_index,
                        "analysis_version": ANALYSIS_VERSION,
                        "interpretation_version": INTERPRETATION_VERSION,
                    },
                    "energy_hartree": parsed.energy_hartree,
                    "items": [item.model_dump(mode="json") for item in items],
                    "groups": [group.model_dump(mode="json") for group in groups],
                }
                _atomic_json(cache_path, payload)

        all_items = payload["items"]
        page = all_items[offset : offset + limit]
        return OrbitalComposition(
            orbital_internal_id=f"{spin}:{orca_index}",
            energy_hartree=float(payload["energy_hartree"]),
            items=page,
            groups=payload["groups"],
            offset=offset,
            limit=limit,
            total=len(all_items),
            has_more=offset + len(page) < len(all_items),
            cache_hit=cache_hit,
        )

    def create_surface(
        self,
        job_id: UUID,
        spin: str,
        orca_index: int,
        basis_index: int,
        request: BasisSurfaceRequest,
    ) -> SurfaceRecord:
        # Composition validates the job, MO/spin mapping, and basis index source.
        composition = self.composition(job_id, spin, orca_index, offset=0, limit=1_000_000)
        item = next((entry for entry in composition.items if entry.basis_index == basis_index), None)
        if item is None:
            raise ChemistryError("AO_BASIS_INDEX_MISMATCH", "The basis index is not in this MO analysis.")
        job_dir = self.jobs._job_dir(job_id)
        gbw = self._final_gbw(job_dir)
        gbw_hash = _sha256(gbw)
        cube_dir = job_dir / "ao-cubes"
        cube_dir.mkdir(exist_ok=True)
        raw_cube = cube_dir / f"{gbw_hash[:16]}.basis-{basis_index}.res40.cube"
        lock = self._lock(str(raw_cube.resolve()))
        with lock:
            if not raw_cube.is_file():
                temporary = raw_cube.with_suffix(f".{threading.get_ident()}.tmp")
                try:
                    self.cube_generator(job_dir, gbw, basis_index, temporary)
                    read_cube(temporary)
                    temporary.replace(raw_cube)
                finally:
                    temporary.unlink(missing_ok=True)
        raw = read_cube(raw_cube)
        scaled = CubeData(raw.origin, raw.axes, raw.shape, raw.values * item.coefficient)
        requested = (
            ["positive", "negative"]
            if request.display_mode == "both"
            else [request.display_mode]
        )
        phases = [
            phase
            for phase in requested
            if (phase == "positive" and float(scaled.values.max()) >= request.isovalue)
            or (phase == "negative" and float(scaled.values.min()) <= -request.isovalue)
        ]
        if not phases:
            raise ChemistryError("AO_EMPTY_ISOSURFACE", "No AO component surface exists at this isovalue.")

        surfaces = job_dir / "surfaces"
        surfaces.mkdir(exist_ok=True)
        urls: dict[str, str] = {}
        cache_hit = True
        identifiers = []
        for phase in phases:
            digest = hashlib.sha256(
                json.dumps(
                    [
                        AO_MESH_VERSION,
                        gbw_hash,
                        spin,
                        orca_index,
                        basis_index,
                        round(item.coefficient, 15),
                        phase,
                        round(request.isovalue, 9),
                    ],
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()[:32]
            identifiers.append(digest)
            output = surfaces / f"{digest}.ply"
            mesh_lock = self._lock(str(output.resolve()))
            with mesh_lock:
                if not output.is_file():
                    cache_hit = False
                    temporary = output.with_suffix(f".{threading.get_ident()}.tmp")
                    try:
                        level = request.isovalue if phase == "positive" else -request.isovalue
                        contour_to_ply(scaled, level, temporary)
                        temporary.replace(output)
                    finally:
                        temporary.unlink(missing_ok=True)
            urls[phase] = f"/api/jobs/{job_id}/surfaces/{digest}/mesh"
        surface_id = hashlib.sha256(":".join(identifiers).encode()).hexdigest()[:32]
        return SurfaceRecord(
            id=surface_id,
            field="ao_component",
            orbital_index=orca_index,
            isovalue=request.isovalue,
            phases=phases,
            cache_hit=cache_hit,
            mesh_urls=urls,
        )

    def _extract_json(self, job_dir: Path, gbw: Path) -> dict:
        tool = orca_tool(self.settings, "orca_2json")
        if not tool:
            raise ChemistryError("ORCA_2JSON_UNAVAILABLE", "orca_2json could not be found.")
        config_path = gbw.with_suffix(".json.conf")
        _atomic_json(config_path, JSON_CONFIG)
        output = gbw.with_suffix(".json")
        # orca_2json does not reliably overwrite an existing GBW JSON. This is a
        # server-owned derived file; the versioned analysis cache remains intact.
        output.unlink(missing_ok=True)
        try:
            completed = subprocess.run(
                [tool, str(gbw), "-json"],
                cwd=job_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ChemistryError("ORCA_2JSON_TIMEOUT", "orca_2json timed out.") from exc
        except OSError as exc:
            raise ChemistryError("ORCA_2JSON_FAILED", str(exc)) from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-1000:]
            raise ChemistryError("ORCA_2JSON_FAILED", detail or f"Exit code {completed.returncode}.")
        if not output.is_file():
            raise ChemistryError("ORCA_2JSON_FAILED", "orca_2json did not create the expected JSON file.")
        try:
            document = json.loads(output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ChemistryError("ORCA_JSON_INVALID", str(exc)) from exc
        if not isinstance(document, dict):
            raise ChemistryError("ORCA_JSON_INVALID", "The GBW JSON root must be an object.")
        return document

    def _generate_ao_cube(self, job_dir: Path, gbw: Path, basis_index: int, output: Path) -> None:
        tool = orca_tool(self.settings, "orca_plot")
        if not tool:
            raise ChemistryError("ORCA_PLOT_UNAVAILABLE", "orca_plot could not be found.")
        before = {path.resolve(): path.stat().st_mtime_ns for path in job_dir.glob("*.cube")}
        # ORCA 6.1 interactive menu: plot type 6 is atomic orbitals. The remaining
        # grid/format/execute choices mirror OPI 2.0's public MO plotting wrapper.
        menu = ["1", "6", "2", str(basis_index), "4", "40", "5", "7", "11", "12", ""]
        try:
            completed = subprocess.run(
                [tool, str(gbw), "-i"],
                cwd=job_dir,
                input="\n".join(menu),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ChemistryError("AO_CUBE_TIMEOUT", "orca_plot AO generation timed out.") from exc
        except OSError as exc:
            raise ChemistryError("AO_CUBE_GENERATION_FAILED", str(exc)) from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()[-1000:]
            raise ChemistryError("AO_CUBE_GENERATION_FAILED", detail or f"Exit code {completed.returncode}.")
        candidates = [
            path
            for path in job_dir.glob("*.cube")
            if path.resolve() not in before or path.stat().st_mtime_ns > before[path.resolve()]
        ]
        if len(candidates) != 1:
            raise ChemistryError(
                "AO_BASIS_MAPPING_FAILED",
                f"Expected one AO Cube for basis index {basis_index}; found {len(candidates)}.",
            )
        shutil.copyfile(candidates[0], output)

    @staticmethod
    def _final_gbw(job_dir: Path) -> Path:
        for name in ("electronic.gbw", "optimization.gbw"):
            candidate = job_dir / name
            if candidate.is_file():
                return candidate
        raise ChemistryError("AO_GBW_MISSING", "No final electronic.gbw or optimization.gbw exists.")

    @staticmethod
    def _analysis_key(gbw_hash: str, spin: str, orca_index: int) -> str:
        payload = [
            gbw_hash,
            spin,
            orca_index,
            ANALYSIS_VERSION,
            INTERPRETATION_VERSION,
        ]
        return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()

    def _lock(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(f"{path.suffix}.{threading.get_ident()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
