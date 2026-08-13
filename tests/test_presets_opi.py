from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from backend.app.chemistry.opi_adapter import ChemistryError, OpiAdapter, _check_output_status
from backend.app.chemistry.presets import PRESETS, get_preset


def test_presets_are_documented_orca_keywords():
    assert PRESETS["preview"]["optimization_keywords"] == ["R2SCAN-3C", "OPT"]
    assert "PBE0" in PRESETS["standard"]["single_point_keywords"]
    assert get_preset("standard")["cost"] == "중간"


def test_opi_adapter_uses_public_structure_and_calculator_api(monkeypatch, water_project, tmp_path):
    captured = {}

    class Structure:
        @classmethod
        def from_lists(cls, symbols, coordinates, charge, multiplicity):
            captured.update(symbols=symbols, coordinates=coordinates, charge=charge, multiplicity=multiplicity)
            return object()

    class Input:
        ncores = 0
        def add_simple_keywords(self, *values): captured["keywords"] = values

    class Calculator:
        def __init__(self, basename, working_dir, version_check=True):
            captured.update(
                basename=basename, working_dir=working_dir, version_check=version_check
            )
            self.input = Input()
            self.structure = None

    modules = {
        "opi": ModuleType("opi"), "opi.core": ModuleType("opi.core"),
        "opi.input": ModuleType("opi.input"), "opi.input.simple_keywords": ModuleType("opi.input.simple_keywords"),
        "opi.input.structures": ModuleType("opi.input.structures"), "opi.input.structures.structure": ModuleType("opi.input.structures.structure"),
    }
    modules["opi.core"].Calculator = Calculator
    modules["opi.input.simple_keywords"].Dft = SimpleNamespace(R2SCAN_3C="R2SCAN_3C")
    modules["opi.input.simple_keywords"].Task = SimpleNamespace(OPT="OPT")
    modules["opi.input.structures.structure"].Structure = Structure
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    calc = OpiAdapter().build_calculator(water_project, tmp_path)
    assert calc.structure is not None
    assert captured["symbols"] == ["O", "H", "H"]
    assert captured["charge"] == 0 and captured["multiplicity"] == 1
    assert captured["keywords"] == ("R2SCAN_3C", "OPT")


def test_output_status_is_independent_of_windows_cp949(tmp_path):
    output_file = tmp_path / "optimization.out"
    contents = (
        b"x" * 178_420
        + "system—Version 5.0\n".encode()
        + b"SUCCESS\nHURRAY\n****ORCA TERMINATED NORMALLY****\n"
    )
    output_file.write_bytes(contents)
    with pytest.raises(UnicodeDecodeError):
        contents.decode("cp949")

    output = SimpleNamespace(get_outfile=lambda: output_file)
    _check_output_status(output, require_geometry=True)


def test_output_status_keeps_structured_convergence_errors(tmp_path):
    output_file = tmp_path / "optimization.out"
    output_file.write_bytes(b"SUCCESS\n****ORCA TERMINATED NORMALLY****\n")
    output = SimpleNamespace(get_outfile=lambda: output_file)

    with pytest.raises(ChemistryError, match="구조 최적화") as error:
        _check_output_status(output, require_geometry=True)
    assert error.value.code == "GEOMETRY_NOT_CONVERGED"
