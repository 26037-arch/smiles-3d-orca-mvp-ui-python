from __future__ import annotations

import math

import numpy as np

from ..models import CalculatedImage, DisplayFrame


DISPLAY_SAMPLES_PER_SEGMENT = 8
ATOMIC_MASSES = {
    "H": 1.00784, "He": 4.002602, "Li": 6.94, "Be": 9.0121831, "B": 10.81,
    "C": 12.011, "N": 14.007, "O": 15.999, "F": 18.998403, "Ne": 20.1797,
    "Na": 22.989769, "Mg": 24.305, "Al": 26.981538, "Si": 28.085, "P": 30.973762,
    "S": 32.06, "Cl": 35.45, "Ar": 39.948, "K": 39.0983, "Ca": 40.078,
}


def image_coordinates(image: CalculatedImage) -> np.ndarray:
    return np.asarray([(atom.x, atom.y, atom.z) for atom in image.atoms], dtype=float)


def mass_weighted_kabsch(reference: np.ndarray, moving: np.ndarray, elements: list[str]) -> np.ndarray:
    """Return a rigidly aligned copy of *moving*; inputs are never modified."""
    rotation, mov_center, ref_center = mass_weighted_kabsch_transform(reference, moving, elements)
    aligned = (moving - mov_center) @ rotation + ref_center
    if not np.all(np.isfinite(aligned)):
        raise ValueError("Kabsch 정렬 결과에 NaN 또는 무한대가 있습니다")
    return aligned


def mass_weighted_kabsch_transform(
    reference: np.ndarray, moving: np.ndarray, elements: list[str]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return rotation, moving centroid and reference centroid for field alignment."""
    if reference.shape != moving.shape or reference.ndim != 2 or reference.shape[1] != 3:
        raise ValueError("Kabsch 정렬 좌표의 shape가 일치하지 않습니다")
    weights = np.asarray([ATOMIC_MASSES.get(element, 1.0) for element in elements], dtype=float)
    weights /= weights.sum()
    ref_center = np.sum(reference * weights[:, None], axis=0)
    mov_center = np.sum(moving * weights[:, None], axis=0)
    ref0 = reference - ref_center
    mov0 = moving - mov_center
    covariance = (mov0 * weights[:, None]).T @ ref0
    left, _, right_t = np.linalg.svd(covariance)
    correction = np.eye(3)
    correction[-1, -1] = np.sign(np.linalg.det(left @ right_t))
    rotation = left @ correction @ right_t
    return rotation, mov_center, ref_center


def align_path(images: list[CalculatedImage], elements: list[str]) -> list[np.ndarray]:
    reference = image_coordinates(images[0])
    return [reference.copy(), *[
        mass_weighted_kabsch(reference, image_coordinates(image), elements)
        for image in images[1:]
    ]]


def normalized_path_coordinate(images: list[CalculatedImage], coordinates: list[np.ndarray]) -> np.ndarray:
    supplied = np.asarray([
        image.reaction_coordinate if image.reaction_coordinate is not None else np.nan
        for image in images
    ])
    if np.all(np.isfinite(supplied)) and np.all(np.diff(supplied) > 0):
        values = supplied
    else:
        lengths = [0.0]
        for left, right in zip(coordinates, coordinates[1:], strict=False):
            lengths.append(lengths[-1] + float(np.linalg.norm(right - left)))
        values = np.asarray(lengths)
    span = float(values[-1] - values[0])
    if not math.isfinite(span) or span <= 1e-14:
        return np.linspace(0.0, 1.0, len(images))
    return (values - values[0]) / span


def _tangents(points: list[np.ndarray], path: np.ndarray) -> list[np.ndarray]:
    result: list[np.ndarray] = []
    for index in range(len(points)):
        if index == 0:
            delta = path[1] - path[0]
            result.append((points[1] - points[0]) / delta)
        elif index == len(points) - 1:
            delta = path[-1] - path[-2]
            result.append((points[-1] - points[-2]) / delta)
        else:
            delta = path[index + 1] - path[index - 1]
            result.append((points[index + 1] - points[index - 1]) / delta)
    return result


def _has_severe_overlap(candidate: np.ndarray, left: np.ndarray, right: np.ndarray) -> bool:
    if len(candidate) < 2:
        return False
    for i in range(len(candidate)):
        for j in range(i + 1, len(candidate)):
            distance = float(np.linalg.norm(candidate[i] - candidate[j]))
            endpoint_min = min(
                float(np.linalg.norm(left[i] - left[j])),
                float(np.linalg.norm(right[i] - right[j])),
            )
            if endpoint_min > 0.55 and distance < 0.28:
                return True
    return False


def interpolate_segment(
    left: np.ndarray,
    right: np.ndarray,
    left_tangent: np.ndarray,
    right_tangent: np.ndarray,
    delta_path: float,
    value: float,
    *,
    force_linear: bool = False,
) -> tuple[np.ndarray, bool]:
    linear = (1 - value) * left + value * right
    if force_linear or delta_path <= 1e-14:
        return linear, True
    displacement = right - left
    tangent_angle_bad = float(np.sum(left_tangent * right_tangent)) < -0.5 * float(
        np.linalg.norm(left_tangent) * np.linalg.norm(right_tangent)
    )
    if tangent_angle_bad:
        return linear, True
    u = value
    candidate = (
        (2 * u**3 - 3 * u**2 + 1) * left
        + (u**3 - 2 * u**2 + u) * delta_path * left_tangent
        + (-2 * u**3 + 3 * u**2) * right
        + (u**3 - u**2) * delta_path * right_tangent
    )
    scale = max(float(np.linalg.norm(displacement, axis=1).max()), 1e-8)
    overshoot = float(np.linalg.norm(candidate - linear, axis=1).max()) > max(0.75, 1.5 * scale)
    if not np.all(np.isfinite(candidate)) or overshoot or _has_severe_overlap(candidate, left, right):
        return linear, True
    return candidate, False


def create_display_frames(
    images: list[CalculatedImage],
    elements: list[str],
    samples_per_segment: int = DISPLAY_SAMPLES_PER_SEGMENT,
) -> list[DisplayFrame]:
    if len(images) < 2:
        raise ValueError("반응 경로에는 계산 지점이 두 개 이상 필요합니다")
    if samples_per_segment < 1:
        raise ValueError("구간별 표시 샘플 수는 1 이상이어야 합니다")
    aligned = align_path(images, elements)
    path = normalized_path_coordinate(images, aligned)
    tangents = _tangents(aligned, path)
    frames: list[DisplayFrame] = []
    for segment in range(len(images) - 1):
        for step in range(samples_per_segment):
            u = step / samples_per_segment
            coordinates, _ = interpolate_segment(
                aligned[segment], aligned[segment + 1], tangents[segment], tangents[segment + 1],
                float(path[segment + 1] - path[segment]), u, force_linear=len(images) == 2,
            )
            left_energy = images[segment].relative_energy_kj_mol
            right_energy = images[segment + 1].relative_energy_kj_mol
            energy = None if left_energy is None or right_energy is None else (1 - u) * left_energy + u * right_energy
            frames.append(DisplayFrame(
                index=len(frames), leftImageIndex=segment, rightImageIndex=segment + 1,
                interpolationValue=u, coordinates=[tuple(row) for row in coordinates.tolist()],
                reactionCoordinate=float((1 - u) * path[segment] + u * path[segment + 1]),
                relativeEnergyKjMol=energy, isCalculated=step == 0,
            ))
    final = aligned[-1]
    frames.append(DisplayFrame(
        index=len(frames), leftImageIndex=len(images) - 1, rightImageIndex=len(images) - 1,
        interpolationValue=0, coordinates=[tuple(row) for row in final.tolist()],
        reactionCoordinate=1, relativeEnergyKjMol=images[-1].relative_energy_kj_mol,
        isCalculated=True,
    ))
    return frames
