from __future__ import annotations

import numpy as np


def atom_line(p1: np.ndarray, p2: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    delta = p2 - p1
    length = float(np.linalg.norm(delta))
    if length <= 1e-8:
        raise ValueError("선택한 두 원자가 겹쳐 직선을 만들 수 없습니다")
    return p1, delta / length


def atom_plane(
    p1: np.ndarray, p2: np.ndarray, p3: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    origin, basis_u = atom_line(p1, p2)
    projected = p3 - p1 - np.dot(p3 - p1, basis_u) * basis_u
    length = float(np.linalg.norm(projected))
    if length <= 1e-8:
        raise ValueError("선택한 세 원자가 일직선이어서 평면을 만들 수 없습니다")
    return origin, basis_u, projected / length


def automatic_range(
    atoms: np.ndarray, origin: np.ndarray, direction: np.ndarray, padding: float
) -> tuple[float, float]:
    projected = (atoms - origin) @ direction
    return float(projected.min() - padding), float(projected.max() + padding)
