from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


BOHR_TO_ANGSTROM = 0.529177210903


class CubeError(ValueError):
    pass


@dataclass(frozen=True)
class CubeData:
    origin: np.ndarray
    axes: np.ndarray
    shape: tuple[int, int, int]
    values: np.ndarray


def read_cube(path: Path) -> CubeData:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        header = lines[2].split()
        atom_count_signed = int(header[0])
        atom_count = abs(atom_count_signed)
        origin = np.asarray([float(x) for x in header[1:4]], dtype=float)
        counts: list[int] = []
        axes: list[list[float]] = []
        angstrom_units = False
        for line in lines[3:6]:
            fields = line.split()
            count = int(fields[0])
            angstrom_units = angstrom_units or count < 0
            counts.append(abs(count))
            axes.append([float(x) for x in fields[1:4]])
        factor = 1.0 if angstrom_units else BOHR_TO_ANGSTROM
        origin *= factor
        axis_array = np.asarray(axes, dtype=float) * factor
        data_start = 6 + atom_count
        raw = np.fromiter(
            (float(token) for line in lines[data_start:] for token in line.split()), dtype=float
        )
        expected = counts[0] * counts[1] * counts[2]
        if raw.size < expected:
            raise CubeError(f"Cube scalar가 부족합니다: {raw.size}/{expected}")
        values = raw[:expected].reshape(tuple(counts), order="C")
        if not np.all(np.isfinite(values)):
            raise CubeError("Cube에 유한하지 않은 scalar가 있습니다")
        return CubeData(origin, axis_array, tuple(counts), values)
    except (OSError, IndexError, ValueError) as exc:
        if isinstance(exc, CubeError):
            raise
        raise CubeError(f"손상된 Cube 파일: {exc}") from exc

