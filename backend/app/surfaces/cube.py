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


def _scalar_tokens(lines: list[str], data_start: int, atom_count_signed: int) -> list[str]:
    """Return scalar tokens after consuming optional Gaussian Cube DSET_IDS."""
    tokens = [token for line in lines[data_start:] for token in line.split()]
    if atom_count_signed >= 0:
        return tokens

    if not tokens:
        raise CubeError("Negative-NATOMS Cube is missing DSET_IDS")
    try:
        dataset_count = int(tokens[0])
    except ValueError as exc:
        raise CubeError("Invalid DSET_IDS dataset count") from exc
    if dataset_count < 1:
        raise CubeError("DSET_IDS dataset count must be positive")

    metadata_size = 1 + dataset_count
    if len(tokens) < metadata_size:
        raise CubeError(
            f"Incomplete DSET_IDS: expected {dataset_count} dataset IDs, "
            f"found {max(0, len(tokens) - 1)}"
        )
    try:
        [int(token) for token in tokens[1:metadata_size]]
    except ValueError as exc:
        raise CubeError("DSET_IDS contains a non-integer dataset ID") from exc

    # CubeData and the contour pipeline represent one scalar field. ORCA's
    # plot_mo output contains one dataset; reject interleaved fields explicitly.
    if dataset_count != 1:
        raise CubeError(
            f"Cube contains {dataset_count} interleaved datasets; exactly one is supported"
        )
    return tokens[metadata_size:]


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
        scalar_tokens = _scalar_tokens(lines, data_start, atom_count_signed)
        raw = np.fromiter((float(token) for token in scalar_tokens), dtype=float)
        expected = counts[0] * counts[1] * counts[2]
        if raw.size != expected:
            raise CubeError(f"Cube scalar count mismatch: found {raw.size}, expected {expected}")
        values = raw.reshape(tuple(counts), order="C")
        if not np.all(np.isfinite(values)):
            raise CubeError("Cube contains a non-finite scalar value")
        return CubeData(origin, axis_array, tuple(counts), values)
    except (OSError, IndexError, ValueError) as exc:
        if isinstance(exc, CubeError):
            raise
        raise CubeError(f"Invalid Cube file: {exc}") from exc
