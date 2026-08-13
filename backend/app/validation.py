from __future__ import annotations

import math

from .models import ATOMIC_NUMBERS, MoleculeProject, ProjectValidation, ValidationMessage


def validate_project(project: MoleculeProject, *, require_atoms: bool = True) -> ProjectValidation:
    messages: list[ValidationMessage] = []
    if require_atoms and not project.atoms:
        messages.append(ValidationMessage(level="error", code="NO_ATOMS", message="원자가 없습니다"))
    electron_count = sum(ATOMIC_NUMBERS[a.element] for a in project.atoms) - project.total_charge
    if electron_count < 0:
        messages.append(
            ValidationMessage(level="error", code="NEGATIVE_ELECTRONS", message="전자 수가 음수입니다")
        )
    # 2S = multiplicity - 1 and N have the same parity.
    if electron_count >= 0 and electron_count % 2 != (project.multiplicity - 1) % 2:
        messages.append(
            ValidationMessage(
                level="error",
                code="CHARGE_MULTIPLICITY_PARITY",
                message=f"전자 수 {electron_count}와 다중도 {project.multiplicity}의 짝·홀수 관계가 맞지 않습니다",
            )
        )
    for i, first in enumerate(project.atoms):
        for second in project.atoms[i + 1 :]:
            distance = math.dist(first.position, second.position)
            if distance < 0.1:
                messages.append(
                    ValidationMessage(
                        level="error",
                        code="OVERLAPPING_ATOMS",
                        message=f"{first.element}와 {second.element} 원자가 {distance:.3f} Å로 겹칩니다",
                    )
                )
            elif distance < 0.35:
                messages.append(
                    ValidationMessage(
                        level="warning",
                        code="CLOSE_ATOMS",
                        message=f"두 원자가 비현실적으로 가깝습니다: {distance:.3f} Å",
                    )
                )
    if any(a.element not in {"H", "C", "N", "O", "F", "P", "S", "Cl", "Br", "I"} for a in project.atoms):
        messages.append(
            ValidationMessage(
                level="warning",
                code="PRESET_CHEMISTRY_WARNING",
                message="음이온·열린껍질·전이금속에는 기본 프리셋이 부적절할 수 있습니다",
            )
        )
    return ProjectValidation(
        valid=not any(m.level == "error" for m in messages),
        electron_count=electron_count,
        messages=messages,
    )

