from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from ..chemistry.opi_adapter import ChemistryError
from ..models import AOContributionGroup, BasisContribution


ANALYSIS_VERSION = "loewdin-v1"
INTERPRETATION_VERSION = "orca61-real-solid-harmonics-v1"
NEGATIVE_EIGENVALUE_TOLERANCE = 1.0e-10
NORMALIZATION_TOLERANCE = 2.0e-5


@dataclass(frozen=True)
class ParsedOrbital:
    energy_hartree: float
    coefficients: np.ndarray
    basis: list[dict[str, Any]]


def loewdin_contributions(
    overlap: np.ndarray,
    coefficients: np.ndarray,
    *,
    negative_tolerance: float = NEGATIVE_EIGENVALUE_TOLERANCE,
    normalization_tolerance: float = NORMALIZATION_TOLERANCE,
) -> tuple[np.ndarray, np.ndarray]:
    """Return phase-normalized MO coefficients and per-AO Lowdin weights."""
    matrix = np.asarray(overlap, dtype=float)
    vector = np.asarray(coefficients, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ChemistryError("AO_MATRIX_DIMENSION_MISMATCH", "Overlap matrix must be square.")
    if vector.ndim != 1 or vector.shape[0] != matrix.shape[0]:
        raise ChemistryError(
            "AO_MATRIX_DIMENSION_MISMATCH",
            "MO coefficient count does not match the overlap-matrix dimension.",
        )
    if not np.all(np.isfinite(matrix)) or not np.all(np.isfinite(vector)):
        raise ChemistryError("AO_DATA_MISSING", "MO coefficients or overlap matrix are not finite.")

    matrix = 0.5 * (matrix + matrix.T)
    eigenvalues, eigenvectors = np.linalg.eigh(matrix)
    scale = max(1.0, float(np.max(np.abs(eigenvalues))))
    tolerance = negative_tolerance * scale
    if float(np.min(eigenvalues)) < -tolerance:
        raise ChemistryError(
            "AO_OVERLAP_NOT_POSITIVE_SEMIDEFINITE",
            f"Overlap matrix has a significant negative eigenvalue ({np.min(eigenvalues):.3e}).",
        )
    eigenvalues = np.where(eigenvalues < 0.0, 0.0, eigenvalues)
    sqrt_overlap = (eigenvectors * np.sqrt(eigenvalues)) @ eigenvectors.T
    transformed = sqrt_overlap @ vector
    weights = np.square(np.abs(transformed))

    norm = float(vector @ matrix @ vector)
    weight_sum = float(weights.sum())
    if (
        not np.isfinite(norm)
        or not np.isfinite(weight_sum)
        or abs(norm - 1.0) > normalization_tolerance
        or abs(weight_sum - 1.0) > normalization_tolerance
    ):
        raise ChemistryError(
            "AO_LOEWDIN_NORMALIZATION_FAILED",
            f"Expected C^T S C and summed Lowdin weights near 1; got {norm:.8g} and {weight_sum:.8g}.",
        )

    # A global MO sign is physically arbitrary. Use the largest Lowdin component
    # as the stable phase reference so UI signs and C_mu phi_mu cubes agree.
    reference = int(np.argmax(weights))
    if vector[reference] < 0.0:
        vector = -vector
    weights = weights / weight_sum
    return vector, weights


def parse_orca_gbw_json(
    document: dict[str, Any], spin: Literal["restricted", "alpha", "beta"], orca_index: int
) -> ParsedOrbital:
    molecule = _mapping(document, "Molecule")
    atoms = _sequence(molecule, "Atoms")
    basis = _expand_basis(atoms)
    overlap = _value(molecule, "S-Matrix", "s-matrix", "S_matrix", "s_matrix")
    if overlap is None:
        raise ChemistryError("AO_OVERLAP_MISSING", "ORCA JSON does not contain S-Matrix.")

    molecular_orbitals = _mapping(molecule, "MolecularOrbitals", "molecularorbitals")
    mos = _sequence(molecular_orbitals, "MOs", "mos")
    hftype = str(_value(molecule, "HFTyp", "hftyp") or "").upper()
    if "UHF" in hftype:
        if len(mos) % 2:
            raise ChemistryError("AO_SPIN_INDEX_MISMATCH", "UHF JSON has an odd MO count.")
        midpoint = len(mos) // 2
        channels = {"alpha": mos[:midpoint], "beta": mos[midpoint:]}
        if spin == "restricted":
            raise ChemistryError("AO_SPIN_INDEX_MISMATCH", "A UHF result requires alpha or beta spin.")
        channel = channels[spin]
    else:
        if spin != "restricted":
            raise ChemistryError("AO_SPIN_INDEX_MISMATCH", "A restricted result has no alpha/beta channel.")
        channel = mos
    if orca_index < 0 or orca_index >= len(channel):
        raise ChemistryError("AO_MO_INDEX_MISMATCH", f"MO index {orca_index} is unavailable for {spin}.")

    mo = channel[orca_index]
    coefficients = _value(mo, "MOCoefficients", "mocoefficients")
    energy = _value(mo, "OrbitalEnergy", "orbitalenergy")
    if coefficients is None or energy is None:
        raise ChemistryError("AO_COEFFICIENTS_MISSING", "Selected MO coefficients or energy are missing.")
    vector = np.asarray(coefficients, dtype=float)
    matrix = np.asarray(overlap, dtype=float)
    if len(basis) != vector.size or matrix.shape != (vector.size, vector.size):
        raise ChemistryError(
            "AO_MATRIX_DIMENSION_MISMATCH",
            f"Basis/MO/overlap dimensions are {len(basis)}, {vector.size}, and {matrix.shape}.",
        )
    normalized, weights = loewdin_contributions(matrix, vector)
    for index, item in enumerate(basis):
        item["coefficient"] = float(normalized[index])
        item["loewdin_weight"] = float(weights[index])
    return ParsedOrbital(float(energy), normalized, basis)


def contribution_models(parsed: ParsedOrbital) -> tuple[list[BasisContribution], list[AOContributionGroup]]:
    ordered = sorted(parsed.basis, key=lambda item: item["loewdin_weight"], reverse=True)
    items = [
        BasisContribution(
            **item,
            percentage=float(item["loewdin_weight"]) * 100.0,
            phase="+" if item["coefficient"] >= 0.0 else "-",
        )
        for item in ordered
    ]
    grouped: dict[tuple[int, str], list[BasisContribution]] = {}
    for item in items:
        grouped.setdefault((item.atom_index, item.ao_label), []).append(item)
    groups = []
    for (atom_index, ao_label), members in grouped.items():
        representative = max(members, key=lambda item: item.loewdin_weight)
        groups.append(
            AOContributionGroup(
                key=f"{atom_index}:{ao_label}",
                atom_index=atom_index,
                atom_label=representative.atom_label,
                element=representative.element,
                ao_label=ao_label,
                basis_indices=[item.basis_index for item in members],
                count=len(members),
                percentage=sum(item.percentage for item in members),
                representative_phase=representative.phase,
            )
        )
    groups.sort(key=lambda group: group.percentage, reverse=True)
    return items, groups


def _expand_basis(atoms: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    basis_index = 0
    for fallback_atom_index, raw_atom in enumerate(atoms):
        if not isinstance(raw_atom, dict):
            raise ChemistryError("AO_BASIS_MAPPING_FAILED", "An ORCA atom entry is not an object.")
        raw_atom_index = _value(raw_atom, "Idx", "idx")
        atom_index = int(fallback_atom_index if raw_atom_index is None else raw_atom_index)
        element = str(_value(raw_atom, "ElementLabel", "elementlabel") or "?")
        atom_label = f"{element}{atom_index + 1}"
        shells = _sequence(raw_atom, "Basis", "basis")
        shell_counts: dict[str, int] = {}
        for raw_shell in shells:
            if not isinstance(raw_shell, dict):
                raise ChemistryError("AO_BASIS_MAPPING_FAILED", "An ORCA basis shell is not an object.")
            shell = str(_value(raw_shell, "Shell", "shell") or "").strip().lower()
            labels = _component_labels(shell)
            shell_counts[shell] = shell_counts.get(shell, 0) + 1
            ordinal = shell_counts[shell]
            for label in labels:
                result.append(
                    {
                        "basis_index": basis_index,
                        "atom_index": atom_index,
                        "atom_label": atom_label,
                        "element": element,
                        "ao_label": f"{label} similar",
                        "shell_label": f"{label} shell-{ordinal}",
                    }
                )
                basis_index += 1
    if not result:
        raise ChemistryError("AO_BASIS_MAPPING_FAILED", "ORCA JSON contains no orbital basis functions.")
    return result


def _component_labels(shell: str) -> list[str]:
    # ORCA 6.1 real solid harmonic order: m=0,+1,-1,+2,-2,... .
    if shell == "s":
        return ["s"]
    if shell == "p":
        return ["p_z", "p_x", "p_y"]
    if shell == "d":
        return ["d_z2", "d_xz", "d_yz", "d_x2-y2", "d_xy"]
    letters = "spdfghiklm"
    if shell not in letters:
        raise ChemistryError("AO_BASIS_MAPPING_FAILED", f"Unsupported ORCA shell label: {shell!r}.")
    angular_momentum = letters.index(shell)
    labels = [f"{shell}_0"]
    for magnetic in range(1, angular_momentum + 1):
        labels.extend([f"{shell}_+{magnetic}", f"{shell}_-{magnetic}"])
    return labels


def _value(mapping: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def _mapping(mapping: dict[str, Any], *names: str) -> dict[str, Any]:
    value = _value(mapping, *names)
    if not isinstance(value, dict):
        raise ChemistryError("AO_DATA_MISSING", f"ORCA JSON is missing {names[0]}.")
    return value


def _sequence(mapping: dict[str, Any], *names: str) -> list[Any]:
    value = _value(mapping, *names)
    if not isinstance(value, list):
        raise ChemistryError("AO_DATA_MISSING", f"ORCA JSON is missing {names[0]}.")
    return value
