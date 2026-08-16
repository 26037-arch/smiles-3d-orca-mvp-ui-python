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


def _rotation_from_vectors(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """
    Compute rotation matrix that aligns source to target using Rodrigues' formula.
    
    Handles degenerate cases:
    - Parallel vectors (no rotation needed)
    - Antiparallel vectors (180° rotation)
    - Degenerate zero vectors (identity)
    """
    source = np.asarray(source, dtype=float)
    target = np.asarray(target, dtype=float)
    
    source_norm = float(np.linalg.norm(source))
    target_norm = float(np.linalg.norm(target))
    
    # Check for degenerate input vectors
    if source_norm <= 1e-14 or target_norm <= 1e-14:
        return np.eye(3)
    
    source_unit = source / source_norm
    target_unit = target / target_norm
    
    dot = float(np.clip(np.dot(source_unit, target_unit), -1.0, 1.0))
    
    # Parallel case: source and target already aligned
    if dot > 1.0 - 1e-12:
        return np.eye(3)
    
    # Antiparallel case: 180° rotation needed
    if dot < -1.0 + 1e-12:
        # For 180° rotation, we need an axis perpendicular to source
        # Choose the canonical basis axis least parallel to source
        abs_source = np.abs(source_unit)
        min_axis_idx = np.argmin(abs_source)
        
        # Create perpendicular axis
        perp = np.zeros(3)
        perp[min_axis_idx] = 1.0
        axis = np.cross(perp, source_unit)
        
        axis_norm = float(np.linalg.norm(axis))
        if axis_norm < 1e-12:
            # Extremely unlikely, but handle gracefully
            return np.eye(3)
        
        axis = axis / axis_norm
        
        # Skew-symmetric matrix of the axis
        K = np.array([
            [0.0, -axis[2], axis[1]],
            [axis[2], 0.0, -axis[0]],
            [-axis[1], axis[0], 0.0],
        ], dtype=float)
        
        # For 180°: R = I + 2K²
        return np.eye(3) + 2.0 * (K @ K)
    
    # General case: compute rotation via Rodrigues' formula
    # R = I + sin(θ)K + (1-cos(θ))K²
    # axis should be normalized cross product: source × target
    axis = np.cross(source_unit, target_unit)
    axis_norm = float(np.linalg.norm(axis))
    
    if axis_norm < 1e-12:
        # Source and target are parallel (already handled above, but be safe)
        return np.eye(3)
    
    axis = axis / axis_norm
    angle = math.acos(dot)
    sin_angle = math.sin(angle)
    cos_angle = math.cos(angle)
    
    # Skew-symmetric matrix of the normalized axis
    K = np.array([
        [0.0, -axis[2], axis[1]],
        [axis[2], 0.0, -axis[0]],
        [-axis[1], axis[0], 0.0],
    ], dtype=float)
    
    # Rodrigues' formula
    R = np.eye(3) + sin_angle * K + (1.0 - cos_angle) * (K @ K)
    
    # Validate result
    if not np.all(np.isfinite(R)):
        raise ValueError("Rotation matrix computation resulted in NaN/Inf values")
    
    # Verify orthogonality
    should_be_identity = R.T @ R
    if not np.allclose(should_be_identity, np.eye(3), atol=1e-10):
        raise ValueError(f"Rotation matrix is not orthogonal: R.T @ R deviation = {np.linalg.norm(should_be_identity - np.eye(3))}")
    
    # Verify proper rotation (det = +1)
    det = float(np.linalg.det(R))
    if not np.isfinite(det) or det < 0.9:  # Allow some numerical tolerance
        raise ValueError(f"Rotation matrix determinant is not +1: det(R) = {det}")
    
    return R


def mass_weighted_kabsch_transform(
    reference: np.ndarray, moving: np.ndarray, elements: list[str]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute rotation matrix, moving centroid, and reference centroid for field alignment.
    
    Returns:
        (rotation, moving_centroid, reference_centroid)
    
    Raises ValueError if inputs are invalid or rotation computation fails.
    """
    if reference.shape != moving.shape or reference.ndim != 2 or reference.shape[1] != 3:
        raise ValueError("Kabsch 정렬 좌표의 shape가 일치하지 않습니다")
    
    weights = np.asarray([ATOMIC_MASSES.get(element, 1.0) for element in elements], dtype=float)
    weights /= weights.sum()
    
    # Compute mass-weighted centroids
    ref_center = np.sum(reference * weights[:, None], axis=0)
    mov_center = np.sum(moving * weights[:, None], axis=0)
    
    # Center the coordinates
    ref0 = reference - ref_center
    mov0 = moving - mov_center
    
    # Compute SVD-based rotation
    covariance = (mov0 * weights[:, None]).T @ ref0
    left, s, right_t = np.linalg.svd(covariance)
    
    # Ensure proper rotation (det = +1, not -1 for reflection)
    correction = np.eye(3)
    correction[-1, -1] = np.sign(np.linalg.det(left @ right_t))
    rotation = left @ correction @ right_t
    
    # Handle degenerate case (rank < 2, e.g., linear molecules)
    if np.linalg.matrix_rank(covariance) < 2:
        # Find the atom with maximum displacement
        moving_norms = np.linalg.norm(mov0, axis=1)
        reference_norms = np.linalg.norm(ref0, axis=1)
        
        moving_max_idx = np.argmax(moving_norms)
        reference_max_idx = np.argmax(reference_norms)
        
        moving_axis = mov0[moving_max_idx]  # Already centered
        reference_axis = ref0[reference_max_idx]  # Already centered
        
        if np.linalg.norm(moving_axis) > 1e-12 and np.linalg.norm(reference_axis) > 1e-12:
            rotation = _rotation_from_vectors(moving_axis, reference_axis)
    
    # Validate rotation matrix
    if not np.all(np.isfinite(rotation)):
        raise ValueError("Kabsch rotation matrix contains NaN or Inf values")
    
    should_be_identity = rotation.T @ rotation
    if not np.allclose(should_be_identity, np.eye(3), atol=1e-10):
        raise ValueError(f"Kabsch rotation is not orthogonal: error = {np.linalg.norm(should_be_identity - np.eye(3))}")
    
    det = float(np.linalg.det(rotation))
    if not np.isfinite(det) or det < 0.9:
        raise ValueError(f"Kabsch rotation determinant is not +1: det(R) = {det}")
    
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
    *,
    interpolate_energy: bool = True,
) -> list[DisplayFrame]:
    if not images:
        raise ValueError("경로에는 계산 지점이 하나 이상 필요합니다")
    if samples_per_segment < 1:
        raise ValueError("구간별 표시 샘플 수는 1 이상이어야 합니다")
    aligned = align_path(images, elements)
    if len(images) == 1:
        return [DisplayFrame(
            index=0,
            leftImageIndex=0,
            rightImageIndex=0,
            interpolationValue=0,
            coordinates=[tuple(row) for row in aligned[0].tolist()],
            reactionCoordinate=0,
            relativeEnergyKjMol=images[0].relative_energy_kj_mol,
            isCalculated=True,
            frameType="actual-geometry",
        )]
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
            energy = (
                None
                if step > 0 and not interpolate_energy
                else None
                if left_energy is None or right_energy is None
                else (1 - u) * left_energy + u * right_energy
            )
            frames.append(DisplayFrame(
                index=len(frames), leftImageIndex=segment, rightImageIndex=segment + 1,
                interpolationValue=u, coordinates=[tuple(row) for row in coordinates.tolist()],
                reactionCoordinate=float((1 - u) * path[segment] + u * path[segment + 1]),
                relativeEnergyKjMol=energy, isCalculated=step == 0,
                frameType="actual-geometry" if step == 0 else "display-interpolation",
            ))
    final = aligned[-1]
    frames.append(DisplayFrame(
        index=len(frames), leftImageIndex=len(images) - 1, rightImageIndex=len(images) - 1,
        interpolationValue=0, coordinates=[tuple(row) for row in final.tolist()],
        reactionCoordinate=1, relativeEnergyKjMol=images[-1].relative_energy_kj_mol,
        isCalculated=True,
        frameType="actual-geometry",
    ))
    return frames
