from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.models import MoleculeProject
from backend.app.validation import validate_project


def test_water_valid_and_electron_count(water_project):
    result = validate_project(water_project)
    assert result.valid
    assert result.electron_count == 10


def test_charge_multiplicity_parity_blocks_calculation(water_project):
    invalid = water_project.model_copy(update={"multiplicity": 2})
    result = validate_project(invalid)
    assert not result.valid
    assert "CHARGE_MULTIPLICITY_PARITY" in {m.code for m in result.messages}


def test_empty_project_and_fluoride():
    empty = MoleculeProject.model_validate({})
    assert not validate_project(empty).valid
    fluoride = MoleculeProject.model_validate(
        {"atoms": [{"id": str(uuid4()), "element": "F", "position": [0, 0, 0]}], "totalCharge": -1, "multiplicity": 1}
    )
    assert validate_project(fluoride).valid


@pytest.mark.parametrize("element", ["Xx", "", "carbon"])
def test_invalid_elements_rejected(element):
    with pytest.raises(ValidationError):
        MoleculeProject.model_validate({"atoms": [{"id": str(uuid4()), "element": element, "position": [0, 0, 0]}]})


@pytest.mark.parametrize("position", [[float("nan"), 0, 0], [float("inf"), 0, 0]])
def test_nonfinite_coordinate_rejected(position):
    with pytest.raises(ValidationError):
        MoleculeProject.model_validate({"atoms": [{"id": str(uuid4()), "element": "H", "position": position}]})


def test_duplicate_ids_and_overlaps_rejected_or_reported():
    atom_id = str(uuid4())
    with pytest.raises(ValidationError):
        MoleculeProject.model_validate({"atoms": [{"id": atom_id, "element": "H", "position": [0, 0, 0]}, {"id": atom_id, "element": "H", "position": [1, 0, 0]}]})
    project = MoleculeProject.model_validate({"atoms": [{"id": str(uuid4()), "element": "H", "position": [0, 0, 0]}, {"id": str(uuid4()), "element": "H", "position": [.05, 0, 0]}]})
    assert "OVERLAPPING_ATOMS" in {m.code for m in validate_project(project).messages}

