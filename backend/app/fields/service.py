from __future__ import annotations

import threading
from pathlib import Path

from ..cache import DerivedCacheManager
from ..models import PlotField
from ..surfaces.cube import CubeData, read_cube
from ..wavefunction import WavefunctionContext, single_wavefunction_context


class CubeFieldService:
    """Generate canonical Cube fields lazily and share them across consumers."""

    def __init__(self, cache: DerivedCacheManager | None = None) -> None:
        self.cache = cache
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def load(
        self,
        job_dir: Path,
        field: PlotField,
        *,
        resolution: int = 40,
    ) -> tuple[CubeData, bool]:
        return self.load_context(
            job_dir,
            single_wavefunction_context(job_dir),
            field,
            resolution=resolution,
        )

    def load_context(
        self,
        job_dir: Path,
        context: WavefunctionContext,
        field: PlotField,
        *,
        resolution: int = 40,
    ) -> tuple[CubeData, bool]:
        path, cache_hit = self.ensure_context(
            job_dir, context, field, resolution=resolution
        )
        return read_cube(path), cache_hit

    def ensure_context(
        self,
        job_dir: Path,
        context: WavefunctionContext,
        field: PlotField,
        *,
        resolution: int = 40,
    ) -> tuple[Path, bool]:
        if field.field == "mo":
            orbital = next(
                (item for item in context.orbitals if item.internal_id == field.orbital_internal_id),
                None,
            )
            if context.orbitals and (
                orbital is None
                or orbital.orca_index != field.orbital_index
                or orbital.spin != field.spin
            ):
                raise ValueError("requested MO does not belong to this geometry")
            if not context.orbitals and field.orbital_internal_id not in context.orbital_refs:
                raise ValueError("requested MO does not belong to this geometry")
            if reference := context.orbital_refs.get(field.orbital_internal_id or ""):
                referenced = (job_dir / reference).resolve()
                try:
                    referenced.relative_to(job_dir.resolve())
                except ValueError as exc:
                    raise ValueError("orbital Cube reference escapes the job directory") from exc
                if referenced.is_file():
                    return referenced, True

        directory = (
            self.cache.directory(job_dir, "cube")
            if self.cache is not None
            else job_dir / "fields"
        )
        directory.mkdir(parents=True, exist_ok=True)
        suffix = (
            "total-density"
            if field.field == "total_density"
            else f"mo.{field.spin}.{field.orbital_index}"
        )
        path = directory / f"{context.cache_prefix}.{suffix}.res{resolution}.cube"
        key = str(path.resolve())
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            if path.is_file():
                if self.cache is not None:
                    self.cache.record(path)
                return path, True
            self._generate_from_gbw(job_dir, context.gbw_path, path, field, resolution)
            if self.cache is not None:
                self.cache.record(path)
            return path, False

    @staticmethod
    def _generate_from_gbw(
        job_dir: Path,
        gbw_path: Path,
        path: Path,
        field: PlotField,
        resolution: int,
    ) -> None:
        try:
            from opi.output.core import Output
        except ImportError as exc:
            raise RuntimeError("Cube generation requires OPI 2.0") from exc
        output = Output(gbw_path.stem, working_dir=job_dir, version_check=False, parse=False)
        output.collect_gbw_json_files()
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
            raise RuntimeError("OPI/orca_plot returned no Cube data")
        path.write_text(cube_text, encoding="utf-8")
