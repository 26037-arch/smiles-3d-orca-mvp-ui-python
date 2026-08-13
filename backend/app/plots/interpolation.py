from __future__ import annotations

import numpy as np

from ..surfaces.cube import CubeData


def trilinear_sample(cube: CubeData, world_points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    fractional = (world_points - cube.origin) @ np.linalg.inv(cube.axes)
    lower = np.floor(fractional).astype(int)
    upper_limit = np.asarray(cube.shape) - 1
    valid = np.all(lower >= 0, axis=1) & np.all(lower < upper_limit, axis=1)
    values = np.full(len(world_points), np.nan, dtype=float)
    if not np.any(valid):
        return values, valid
    indices = lower[valid]
    fraction = fractional[valid] - indices
    sampled = np.zeros(len(indices), dtype=float)
    for di in (0, 1):
        for dj in (0, 1):
            for dk in (0, 1):
                weight = (
                    (fraction[:, 0] if di else 1 - fraction[:, 0])
                    * (fraction[:, 1] if dj else 1 - fraction[:, 1])
                    * (fraction[:, 2] if dk else 1 - fraction[:, 2])
                )
                sampled += weight * cube.values[
                    indices[:, 0] + di,
                    indices[:, 1] + dj,
                    indices[:, 2] + dk,
                ]
    values[valid] = sampled
    return values, valid
