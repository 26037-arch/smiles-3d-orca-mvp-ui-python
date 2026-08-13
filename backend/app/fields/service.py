from __future__ import annotations

import threading
from pathlib import Path

from ..models import PlotField
from ..surfaces.cube import CubeData, read_cube


class CubeFieldService:
    """Generate canonical Cube fields lazily and share them across consumers."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def load(
        self,
        job_dir: Path,
        field: PlotField,
        *,
        resolution: int = 40,
    ) -> tuple[CubeData, bool]:
        basename = "electronic" if (job_dir / "electronic.gbw").exists() else "optimization"
        fields_dir = job_dir / "fields"
        fields_dir.mkdir(exist_ok=True)
        if field.field == "total_density":
            path = fields_dir / f"total-density.{basename}.res{resolution}.cube"
        else:
            path = fields_dir / (
                f"mo.{field.spin}.{field.orbital_index}.{basename}.res{resolution}.cube"
            )
        key = str(path.resolve())
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            if path.is_file():
                return read_cube(path), True
            self._generate(job_dir, basename, path, field, resolution)
            return read_cube(path), False

    @staticmethod
    def _generate(
        job_dir: Path,
        basename: str,
        path: Path,
        field: PlotField,
        resolution: int,
    ) -> None:
        try:
            from opi.output.core import Output
        except ImportError as exc:
            raise RuntimeError("Cube 생성에 필요한 OPI 2.0을 import할 수 없습니다") from exc
        output = Output(basename, working_dir=job_dir, version_check=False, parse=False)
        output.collect_gbw_json_files()
        if not output.gbw_json_files:
            raise RuntimeError("그래프 생성에 필요한 ORCA GBW 파일을 찾지 못했습니다")
        if field.field == "total_density":
            cube_output = output.plot_density(resolution=resolution, timeout=600)
        else:
            cube_output = output.plot_mo(
                field.orbital_index,
                operator=1 if field.spin == "beta" else 0,
                resolution=resolution,
                gbw_type="gbw",
                timeout=600,
            )
        cube_text = getattr(cube_output, "cube", None) if cube_output is not None else None
        if not cube_text:
            raise RuntimeError("OPI/orca_plot이 Cube 데이터를 반환하지 않았습니다")
        path.write_text(cube_text, encoding="utf-8")
