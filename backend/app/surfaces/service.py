from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from ..jobs.manager import JobManager
from ..models import JobMode, SurfaceRecord, SurfaceRequest
from .cube import read_cube
from .mesh import cache_key, contour_to_ply, demo_surface_ply


class SurfaceService:
    def __init__(self, jobs: JobManager):
        self.jobs = jobs

    def create(self, job_id: UUID, request: SurfaceRequest) -> SurfaceRecord:
        record = self.jobs.get(job_id)
        self.jobs.result(job_id)
        job_dir = self.jobs._job_dir(job_id)
        surfaces = job_dir / "surfaces"
        surfaces.mkdir(exist_ok=True)
        phases = ["positive"] if request.field == "total_density" else (
            ["positive", "negative"] if request.display_mode == "both" else [request.display_mode]
        )
        urls: dict[str, str] = {}
        all_hit = True
        ids: list[str] = []
        for phase in phases:
            if record.mode == JobMode.DEMO:
                cube_hash = "demo-v1"
            else:
                cube_path = self._find_or_generate_cube(job_dir, request)
                cube_hash = hashlib.sha256(cube_path.read_bytes()).hexdigest()
            key = cache_key(cube_hash, request.field, request.orbital_index, request.spin, phase, request.isovalue)
            ids.append(key)
            output = surfaces / f"{key}.ply"
            if not output.exists():
                all_hit = False
                if record.mode == JobMode.DEMO:
                    demo_surface_ply(
                        output, field=request.field, sign=1 if phase == "positive" else -1,
                        orbital=request.orbital_index or 0,
                    )
                else:
                    cube = read_cube(cube_path)
                    level = request.isovalue if phase == "positive" else -request.isovalue
                    contour_to_ply(cube, level, output)
            urls[phase] = f"/api/jobs/{job_id}/surfaces/{key}/mesh"
        surface_id = hashlib.sha256(":".join(ids).encode()).hexdigest()[:32]
        return SurfaceRecord(
            id=surface_id, field=request.field, orbital_index=request.orbital_index,
            isovalue=request.isovalue, phases=phases, cache_hit=all_hit, mesh_urls=urls,
        )

    def mesh_path(self, job_id: UUID, surface_id: str) -> Path:
        if len(surface_id) != 32 or any(c not in "0123456789abcdef" for c in surface_id):
            raise FileNotFoundError(surface_id)
        path = (self.jobs._job_dir(job_id) / "surfaces" / f"{surface_id}.ply").resolve()
        expected = (self.jobs._job_dir(job_id) / "surfaces").resolve()
        if path.parent != expected or not path.is_file():
            raise FileNotFoundError(surface_id)
        return path

    @staticmethod
    def _find_or_generate_cube(job_dir: Path, request: SurfaceRequest) -> Path:
        patterns = ["*density*.cube", "*.eldens.cube"] if request.field == "total_density" else [f"*{request.orbital_index}*.cube"]
        for pattern in patterns:
            if candidate := next(iter(job_dir.glob(pattern)), None):
                return candidate
        try:
            from opi.output.core import Output
        except ImportError as exc:
            raise RuntimeError("Cube 생성에 필요한 OPI 2.0을 import할 수 없습니다") from exc
        basename = "electronic" if (job_dir / "electronic.gbw").exists() else "optimization"
        output = Output(basename, working_dir=job_dir, version_check=False, parse=False)
        if request.field == "total_density":
            cube_output = output.plot_density(resolution=40, timeout=600)
            cube_path = job_dir / f"{basename}.density.cube"
        else:
            cube_output = output.plot_mo(
                request.orbital_index, resolution=40, gbw_type="gbw", timeout=600
            )
            cube_path = job_dir / f"{basename}.mo.{request.orbital_index}.cube"
        cube_text = getattr(cube_output, "cube", None) if cube_output is not None else None
        if not cube_text:
            raise RuntimeError("OPI/orca_plot이 Cube 데이터를 반환하지 않았습니다")
        cube_path.write_text(cube_text, encoding="utf-8")
        return cube_path
