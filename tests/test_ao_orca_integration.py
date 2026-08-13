from __future__ import annotations

import re
import subprocess

import pytest

from backend.app.ao.analysis import contribution_models, parse_orca_gbw_json
from backend.app.ao.service import AOAnalysisService
from backend.app.chemistry.diagnostics import orca_tool
from backend.app.config import load_settings
from backend.app.surfaces.cube import read_cube


@pytest.mark.orca
def test_real_orca61_json_loewdin_and_atomic_orbital_cube(tmp_path):
    settings = load_settings()
    orca = settings.orca_path
    if not orca or not orca_tool(settings, "orca_2json") or not orca_tool(settings, "orca_plot"):
        pytest.skip("A licensed ORCA 6.1 installation with companion tools is required")

    input_path = tmp_path / "h2.inp"
    input_path.write_text(
        "! HF STO-3G TightSCF\n"
        "%output\n"
        "  Print[P_ReducedOrbPopMO_L] 1\n"
        "end\n"
        "* xyz 0 1\n"
        "H 0.0 0.0 0.0\n"
        "H 0.0 0.0 0.74\n"
        "*\n",
        encoding="ascii",
    )
    completed = subprocess.run(
        [orca, input_path.name],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        shell=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    assert b"****ORCA TERMINATED NORMALLY****" in completed.stdout
    output_text = completed.stdout.decode("utf-8", errors="replace")
    output_lines = output_text.splitlines()
    population_start = next(
        index
        for index, line in enumerate(output_lines)
        if "LOEWDIN REDUCED ORBITAL POPULATIONS PER MO" in line
    )
    population_lines = output_lines[population_start : population_start + 20]
    printed_percentages = []
    for line in population_lines:
        match = re.match(r"\s*\d+\s+\S+\s+\S+\s+([-+]?\d+(?:\.\d+)?)", line)
        if match:
            printed_percentages.append(float(match.group(1)))

    service = AOAnalysisService(object(), settings)  # job access is not needed here
    gbw = tmp_path / "h2.gbw"
    document = service._extract_json(tmp_path, gbw)
    parsed = parse_orca_gbw_json(document, "restricted", 0)
    items, groups = contribution_models(parsed)
    assert len(items) == 2
    assert sum(item.percentage for item in items) == pytest.approx(100.0, abs=1.0e-8)
    computed_percentages = sorted(group.percentage for group in groups)
    assert computed_percentages == pytest.approx([50.0, 50.0], abs=0.1)
    assert sorted(printed_percentages) == pytest.approx(computed_percentages, abs=0.1)

    cube_path = tmp_path / "basis-0.cube"
    service._generate_ao_cube(tmp_path, gbw, 0, cube_path)
    assert (tmp_path / "h2.ao0.cube").is_file()
    cube = read_cube(cube_path)
    assert cube.values.size > 0
    assert float(abs(cube.values).max()) > 0.0
