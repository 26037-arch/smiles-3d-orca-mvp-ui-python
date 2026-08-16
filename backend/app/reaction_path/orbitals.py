from __future__ import annotations

from functools import lru_cache
from typing import Protocol

import numpy as np

from ..models import OrbitalMatch
from ..surfaces.cube import CubeData


ORBITAL_OVERLAP_THRESHOLD = 0.60


class OrbitalOverlapProvider(Protocol):
    def compute_signed_overlap(self, left: CubeData, right: CubeData) -> float: ...


def grids_match(left: CubeData, right: CubeData) -> bool:
    return (
        left.shape == right.shape
        and np.allclose(left.origin, right.origin, atol=1e-9)
        and np.allclose(left.axes, right.axes, atol=1e-9)
    )


def trilinear_resample(source: CubeData, target: CubeData) -> np.ndarray:
    """Resample an orthogonal Cube field onto target grid coordinates."""
    if not np.allclose(source.axes, np.diag(np.diag(source.axes)), atol=1e-10):
        raise ValueError("현재 공통 cube 격자는 축에 정렬된 직교 격자만 지원합니다")
    points = np.indices(target.shape, dtype=float).reshape(3, -1).T
    world = target.origin + points @ target.axes
    source_index = (world - source.origin) @ np.linalg.inv(source.axes)
    return _sample_indices(source, source_index, target.shape)


def _sample_indices(source: CubeData, source_index: np.ndarray, shape: tuple[int, int, int]) -> np.ndarray:
    result = np.zeros(len(source_index), dtype=float)
    valid = np.all((source_index >= 0) & (source_index <= np.asarray(source.shape) - 1), axis=1)
    for output_index in np.flatnonzero(valid):
        position = source_index[output_index]
        lower = np.floor(position).astype(int)
        upper = np.minimum(lower + 1, np.asarray(source.shape) - 1)
        fraction = position - lower
        value = 0.0
        for dx in (0, 1):
            for dy in (0, 1):
                for dz in (0, 1):
                    index = [upper[0] if dx else lower[0], upper[1] if dy else lower[1], upper[2] if dz else lower[2]]
                    weight = (
                        (fraction[0] if dx else 1 - fraction[0])
                        * (fraction[1] if dy else 1 - fraction[1])
                        * (fraction[2] if dz else 1 - fraction[2])
                    )
                    value += weight * source.values[tuple(index)]
        result[output_index] = value
    return result.reshape(shape)


def transformed_common_grid(
    cubes: list[CubeData],
    transforms: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    padding: float = 2.0,
) -> CubeData:
    if len(cubes) != len(transforms) or not cubes:
        raise ValueError("cube와 정렬 변환의 개수가 일치해야 합니다")
    corners: list[np.ndarray] = []
    spacing: list[list[float]] = []
    for cube, (rotation, moving_center, reference_center) in zip(cubes, transforms, strict=True):
        if not np.allclose(cube.axes, np.diag(np.diag(cube.axes)), atol=1e-10):
            raise ValueError("현재 공통 cube 격자는 축에 정렬된 직교 격자만 지원합니다")
        spacing.append([abs(cube.axes[index, index]) for index in range(3)])
        index_corners = np.asarray([
            [x, y, z]
            for x in (0, cube.shape[0] - 1)
            for y in (0, cube.shape[1] - 1)
            for z in (0, cube.shape[2] - 1)
        ], dtype=float)
        world = cube.origin + index_corners @ cube.axes
        corners.append((world - moving_center) @ rotation + reference_center)
    all_corners = np.concatenate(corners)
    lower = all_corners.min(axis=0) - padding
    upper = all_corners.max(axis=0) + padding
    voxel = np.min(np.asarray(spacing), axis=0)
    shape = tuple((np.ceil((upper - lower) / voxel).astype(int) + 1).tolist())
    return CubeData(lower, np.diag(voxel), shape, np.zeros(shape, dtype=float))


def trilinear_resample_transformed(
    source: CubeData,
    target: CubeData,
    transform: tuple[np.ndarray, np.ndarray, np.ndarray],
) -> np.ndarray:
    rotation, moving_center, reference_center = transform
    points = np.indices(target.shape, dtype=float).reshape(3, -1).T
    aligned_world = target.origin + points @ target.axes
    source_world = (aligned_world - reference_center) @ rotation.T + moving_center
    source_index = (source_world - source.origin) @ np.linalg.inv(source.axes)
    return _sample_indices(source, source_index, target.shape)


class GridOrbitalOverlapProvider:
    def compute_signed_overlap(self, left: CubeData, right: CubeData) -> float:
        right_values = right.values if grids_match(left, right) else trilinear_resample(right, left)
        left_values = left.values
        volume = abs(float(np.linalg.det(left.axes)))
        numerator = float(np.sum(left_values * right_values) * volume)
        denominator = float(np.sqrt(np.sum(left_values**2) * volume * np.sum(right_values**2) * volume))
        if denominator <= 0 or not np.isfinite(denominator):
            raise ValueError("정규화할 수 없는 빈 오비탈 scalar field입니다")
        return max(-1.0, min(1.0, numerator / denominator))


def common_grid(cubes: list[CubeData], padding: float = 2.0) -> CubeData:
    if not cubes:
        raise ValueError("공통 격자를 만들 cube가 없습니다")
    for cube in cubes:
        if not np.allclose(cube.axes, np.diag(np.diag(cube.axes)), atol=1e-10):
            raise ValueError("현재 공통 cube 격자는 축에 정렬된 직교 격자만 지원합니다")
    spacing = np.min(np.asarray([[abs(cube.axes[i, i]) for i in range(3)] for cube in cubes]), axis=0)
    lower = np.min(np.asarray([cube.origin for cube in cubes]), axis=0) - padding
    upper = np.max(np.asarray([
        cube.origin + (np.asarray(cube.shape) - 1) @ cube.axes for cube in cubes
    ]), axis=0) + padding
    shape = tuple((np.ceil((upper - lower) / spacing).astype(int) + 1).tolist())
    axes = np.diag(spacing)
    return CubeData(lower, axes, shape, np.zeros(shape, dtype=float))


def align_phase(values: np.ndarray, signed_overlap: float) -> np.ndarray:
    return (-values if signed_overlap < 0 else values).copy()


def interpolate_scalar_fields(left: np.ndarray, right: np.ndarray, value: float, *, preserve_l2_norm: bool = True) -> np.ndarray:
    if left.shape != right.shape:
        raise ValueError("보간할 scalar field의 shape가 다릅니다")
    if not 0 <= value <= 1:
        raise ValueError("scalar field 보간값은 0..1이어야 합니다")
    result = (1 - value) * left + value * right
    if not np.all(np.isfinite(result)):
        raise ValueError("보간된 scalar field에 NaN 또는 무한대가 있습니다")
    if not preserve_l2_norm:
        return result
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    target_norm = (1 - value) * left_norm + value * right_norm
    current_norm = float(np.linalg.norm(result))
    if current_norm <= 1e-14:
        if target_norm <= 1e-14:
            return result
        return np.where(np.abs(left) >= np.abs(right), left, right).astype(float, copy=False)
    result = result * (target_norm / current_norm)
    return result


def maximum_weight_assignment(weights: np.ndarray) -> list[tuple[int, int]]:
    """Exact one-to-one maximum assignment using O(rows * 2**columns) DP."""
    matrix = np.asarray(weights, dtype=float)
    if matrix.ndim != 2:
        raise ValueError("overlap matrix는 2차원이어야 합니다")
    transposed = matrix.shape[0] > matrix.shape[1]
    work = matrix.T if transposed else matrix
    rows, columns = work.shape
    if columns > 11:
        raise ValueError("MO 후보 창은 최대 11개까지 지원합니다")
    @lru_cache(maxsize=None)
    def solve(row: int, used: int) -> tuple[float, tuple[int, ...]]:
        if row == rows:
            return 0.0, ()
        best_score = float("-inf")
        best_choice: tuple[int, ...] = ()
        for column in range(columns):
            if used & (1 << column):
                continue
            tail_score, tail = solve(row + 1, used | (1 << column))
            score = float(work[row, column]) + tail_score
            if score > best_score:
                best_score, best_choice = score, (column, *tail)
        return best_score, best_choice

    _, best = solve(0, 0)
    pairs = [(row, column) for row, column in enumerate(best)]
    return [(column, row) for row, column in pairs] if transposed else pairs


def match_orbitals(
    left_ids: list[str], right_ids: list[str], signed_overlaps: np.ndarray,
    threshold: float = ORBITAL_OVERLAP_THRESHOLD,
) -> list[OrbitalMatch]:
    absolute = np.abs(signed_overlaps)
    assignments = dict(maximum_weight_assignment(absolute))
    matches: list[OrbitalMatch] = []
    for left_index, left_id in enumerate(left_ids):
        right_index = assignments.get(left_index)
        if right_index is None:
            matches.append(OrbitalMatch(leftOrbitalId=left_id, status="below-threshold"))
            continue
        overlap = float(signed_overlaps[left_index, right_index])
        accepted = abs(overlap) >= threshold
        row = np.sort(absolute[left_index])[::-1]
        ambiguous = accepted and len(row) > 1 and row[0] - row[1] < 0.05
        matches.append(OrbitalMatch(
            leftOrbitalId=left_id, rightOrbitalId=right_ids[right_index] if accepted else None,
            signedOverlap=overlap, absoluteOverlap=abs(overlap),
            status="ambiguous" if ambiguous else "matched" if accepted else "below-threshold",
        ))
    return matches


class OrbitalTracker:
    """A branch stays terminal once an overlap falls below threshold."""

    def __init__(self, orbital_id: str, threshold: float = ORBITAL_OVERLAP_THRESHOLD):
        self.current_orbital_id = orbital_id
        self.threshold = threshold
        self.active = True

    def advance(self, right_orbital_id: str, signed_overlap: float) -> OrbitalMatch:
        left = self.current_orbital_id
        if not self.active or abs(signed_overlap) < self.threshold:
            self.active = False
            return OrbitalMatch(
                leftOrbitalId=left, rightOrbitalId=None, signedOverlap=signed_overlap,
                absoluteOverlap=abs(signed_overlap), status="below-threshold",
            )
        self.current_orbital_id = right_orbital_id
        return OrbitalMatch(
            leftOrbitalId=left, rightOrbitalId=right_orbital_id,
            signedOverlap=signed_overlap, absoluteOverlap=abs(signed_overlap), status="matched",
        )
