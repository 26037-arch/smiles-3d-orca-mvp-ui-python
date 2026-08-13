from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .cube import CubeData


def cache_key(cube_hash: str, field: str, orbital: int | None, spin: str, sign: str, isovalue: float) -> str:
    payload = json.dumps(
        [cube_hash, field, orbital, spin, sign, round(isovalue, 9)], separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def contour_to_ply(cube: CubeData, isovalue: float, output: Path) -> None:
    try:
        import pyvista as pv
    except ImportError as exc:
        raise RuntimeError("PyVista/VTK가 설치되지 않아 등밀도면을 만들 수 없습니다") from exc
    nx, ny, nz = cube.shape
    i, j, k = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    points = (
        cube.origin
        + i[..., None] * cube.axes[0]
        + j[..., None] * cube.axes[1]
        + k[..., None] * cube.axes[2]
    )
    grid = pv.StructuredGrid(
        points[..., 0],
        points[..., 1],
        points[..., 2],
    )
    grid["field"] = cube.values.ravel(order="F")
    mesh = grid.contour([isovalue], scalars="field").compute_normals()
    if mesh.n_points == 0:
        raise ValueError("요청한 등밀도값에서 표면이 비어 있습니다")
    mesh.clear_data()
    mesh.save(output, binary=True)


def demo_surface_ply(output: Path, *, field: str, sign: int = 1, orbital: int = 0) -> None:
    """Write a small ASCII PLY mesh for UI tests; deliberately not quantum data."""
    centers = [(0.0, 0.0, 0.0)] if field == "total_density" else [((1 if sign > 0 else -1) * 0.65, 0, 0)]
    radius = 1.45 if field == "total_density" else 0.75 + (orbital % 3) * 0.08
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    lat_steps, lon_steps = 16, 24
    for center in centers:
        base = len(vertices)
        for lat in range(lat_steps + 1):
            phi = math.pi * lat / lat_steps
            for lon in range(lon_steps):
                theta = 2 * math.pi * lon / lon_steps
                vertices.append((
                    center[0] + radius * math.sin(phi) * math.cos(theta),
                    center[1] + radius * math.sin(phi) * math.sin(theta),
                    center[2] + radius * math.cos(phi),
                ))
        for lat in range(lat_steps):
            for lon in range(lon_steps):
                a = base + lat * lon_steps + lon
                b = base + lat * lon_steps + (lon + 1) % lon_steps
                c = base + (lat + 1) * lon_steps + lon
                d = base + (lat + 1) * lon_steps + (lon + 1) % lon_steps
                faces.extend([(a, c, b), (b, c, d)])
    lines = [
        "ply", "format ascii 1.0", f"comment GeoORCA demo {field}",
        f"element vertex {len(vertices)}", "property float x", "property float y", "property float z",
        f"element face {len(faces)}", "property list uchar int vertex_indices", "end_header",
    ]
    lines.extend(f"{x:.6f} {y:.6f} {z:.6f}" for x, y, z in vertices)
    lines.extend(f"3 {a} {b} {c}" for a, b, c in faces)
    output.write_text("\n".join(lines) + "\n", encoding="ascii")
