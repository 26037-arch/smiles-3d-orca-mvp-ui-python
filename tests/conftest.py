from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.models import MoleculeProject


@pytest.fixture
def water_project() -> MoleculeProject:
    return MoleculeProject.model_validate(
        {
            "schemaVersion": 1,
            "name": "Water",
            "atoms": [
                {"id": str(uuid4()), "element": "O", "position": [0, 0, 0]},
                {"id": str(uuid4()), "element": "H", "position": [0.96, 0, 0]},
                {"id": str(uuid4()), "element": "H", "position": [-0.24, 0.93, 0]},
            ],
            "bonds": [],
            "sketchPlanes": [],
            "totalCharge": 0,
            "multiplicity": 1,
            "calculationPreset": "preview",
            "displaySettings": {},
        }
    )

