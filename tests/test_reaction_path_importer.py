from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import backend.app.reaction_path.importer as importer
from backend.app.reaction_path import ReactionPathError
from backend.app.reaction_path.importer import (
    HARTREE_TO_KJ_MOL,
    ReactionPathManifestGenerator,
    parse_multi_xyz,
)


def trajectory(
    comments: tuple[str, str] = ("Energy = -10.000000 Eh", "Energy = -9.900000 Eh"),
    newline: str = "\n",
) -> str:
    rows = [
        "2", comments[0], "H 0.0 0.0 0.0", "F 1.0 0.0 0.0",
        "2", comments[1], "H 0.1 0.0 0.0", "F 1.1 0.0 0.0",
    ]
    return newline.join(rows) + newline


@pytest.mark.parametrize(
    "name, expected_type",
    [("rxn_MEP_trj.xyz", "neb"), ("rxn_IRC_Full_trj.xyz", "irc")],
)
def test_generates_manifest_for_final_orca_trajectories(tmp_path, name, expected_type):
    source = tmp_path / name
    source.write_text(trajectory(), encoding="utf-8")

    manifest = ReactionPathManifestGenerator().ensure(tmp_path)
    raw = json.loads(manifest.read_text(encoding="utf-8"))

    assert manifest == tmp_path / "reaction-path.json"
    assert raw["schemaVersion"] == 1
    assert raw["sourceType"] == expected_type
    assert raw["sourceTrajectory"] == name
    assert raw["energyReference"] == "first-image"
    assert raw["energyUnit"] == "hartree"
    assert raw["relativeEnergyUnit"] == "kJ/mol"
    assert raw["reactionCoordinateSource"] == "derived-aligned-cartesian"
    assert raw["images"][0]["reactionCoordinate"] == 0
    assert raw["images"][-1]["reactionCoordinate"] == 1
    assert raw["images"][0]["relativeEnergyKjMol"] == 0
    assert raw["images"][1]["relativeEnergyKjMol"] == pytest.approx(
        0.1 * HARTREE_TO_KJ_MOL
    )
    assert raw["images"][0]["wavefunctionRef"] is None
    assert raw["sourceMetadata"]["sha256"]


def test_parser_supports_crlf_and_blank_comments(tmp_path):
    source = tmp_path / "rxn_MEP_trj.xyz"
    source.write_bytes(trajectory(("", ""), "\r\n").encode())
    frames = parse_multi_xyz(source)
    assert len(frames) == 2
    assert all(frame.energy_hartree is None for frame in frames)


def test_energy_parser_is_explicit_and_preserves_missing_values(tmp_path):
    source = tmp_path / "rxn_MEP_trj.xyz"
    source.write_text(
        trajectory(("Coordinates from ORCA-job rxn E -10.25", "frame 12 value -9.5")),
        encoding="utf-8",
    )
    frames = parse_multi_xyz(source)
    assert frames[0].energy_hartree == -10.25
    assert frames[1].energy_hartree is None
    raw = json.loads(ReactionPathManifestGenerator().ensure(tmp_path).read_text())
    assert raw["images"][1]["energyHartree"] is None
    assert raw["images"][1]["relativeEnergyKjMol"] is None


def test_relative_energy_uses_first_image_not_path_minimum(tmp_path):
    source = tmp_path / "rxn_MEP_trj.xyz"
    source.write_text(
        trajectory(("Energy = -10.0 Eh", "Energy = -10.2 Eh")), encoding="utf-8"
    )
    raw = json.loads(ReactionPathManifestGenerator().ensure(tmp_path).read_text())
    assert raw["images"][0]["relativeEnergyKjMol"] == 0
    assert raw["images"][1]["relativeEnergyKjMol"] == pytest.approx(
        -0.2 * HARTREE_TO_KJ_MOL
    )


@pytest.mark.parametrize(
    "body, code",
    [
        ("x\ncomment\n", "INVALID_XYZ_ATOM_COUNT"),
        ("2\ncomment\nH 0 0 0\n", "TRUNCATED_XYZ_FRAME"),
        (trajectory().replace("H 0.1 0.0 0.0", "H NaN 0.0 0.0"), "INVALID_XYZ_COORDINATE"),
        (trajectory().replace("F 1.1 0.0 0.0", "Cl 1.1 0.0 0.0"), "ELEMENT_ORDER_MISMATCH"),
        (
            "2\nfirst\nH 0 0 0\nF 1 0 0\n1\nsecond\nH 0.1 0 0\n",
            "ATOM_COUNT_MISMATCH",
        ),
    ],
)
def test_parser_reports_malformed_frames(tmp_path, body, code):
    source = tmp_path / "rxn_MEP_trj.xyz"
    source.write_text(body, encoding="utf-8")
    with pytest.raises(ReactionPathError) as caught:
        parse_multi_xyz(source)
    assert caught.value.code == code


def test_does_not_treat_mep_all_as_final_path(tmp_path):
    (tmp_path / "rxn_MEP_ALL_trj.xyz").write_text(trajectory(), encoding="utf-8")
    with pytest.raises(ReactionPathError) as caught:
        ReactionPathManifestGenerator().ensure(tmp_path)
    assert caught.value.code == "FINAL_NEB_TRAJECTORY_MISSING"
    assert not (tmp_path / "reaction-path.json").exists()


def test_stale_manifest_is_regenerated_when_source_changes(tmp_path):
    source = tmp_path / "rxn_MEP_trj.xyz"
    source.write_text(trajectory(), encoding="utf-8")
    generator = ReactionPathManifestGenerator()
    manifest = generator.ensure(tmp_path)
    first = json.loads(manifest.read_text())
    source.write_text(trajectory(("Energy = -10", "Energy = -9.7")) + "\n", encoding="utf-8")
    second = json.loads(generator.ensure(tmp_path).read_text())
    assert second["sourceMetadata"]["sha256"] != first["sourceMetadata"]["sha256"]
    assert second["images"][1]["relativeEnergyKjMol"] == pytest.approx(
        0.3 * HARTREE_TO_KJ_MOL
    )


def test_corrupt_or_old_manifest_is_rebuilt_from_source(tmp_path):
    source = tmp_path / "rxn_MEP_trj.xyz"
    source.write_text(trajectory(), encoding="utf-8")
    manifest = tmp_path / "reaction-path.json"
    manifest.write_text("{broken", encoding="utf-8")
    generator = ReactionPathManifestGenerator()
    rebuilt = json.loads(generator.ensure(tmp_path).read_text(encoding="utf-8"))
    assert rebuilt["schemaVersion"] == 1
    rebuilt["schemaVersion"] = 999
    manifest.write_text(json.dumps(rebuilt), encoding="utf-8")
    assert json.loads(generator.ensure(tmp_path).read_text())["schemaVersion"] == 1


def test_concurrent_generation_parses_once(tmp_path, monkeypatch):
    (tmp_path / "rxn_IRC_Full_trj.xyz").write_text(trajectory(), encoding="utf-8")
    calls = 0
    call_lock = threading.Lock()
    original = importer.parse_multi_xyz

    def counted(path):
        nonlocal calls
        with call_lock:
            calls += 1
        return original(path)

    monkeypatch.setattr(importer, "parse_multi_xyz", counted)
    with ThreadPoolExecutor(max_workers=6) as executor:
        manifests = list(executor.map(lambda _: ReactionPathManifestGenerator().ensure(tmp_path), range(6)))
    assert len(set(manifests)) == 1
    assert calls == 1


def test_atomic_write_failure_preserves_existing_manifest(tmp_path, monkeypatch):
    source = tmp_path / "rxn_MEP_trj.xyz"
    source.write_text(trajectory(), encoding="utf-8")
    generated = ReactionPathManifestGenerator().ensure(tmp_path)
    valid = json.loads(generated.read_text(encoding="utf-8"))
    destination = tmp_path / "reaction-path.json"
    destination.write_text('{"existing": true}\n', encoding="utf-8")

    def fail_replace(_source, _destination):
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(importer.os, "replace", fail_replace)
    with pytest.raises(ReactionPathError) as caught:
        ReactionPathManifestGenerator._atomic_write(destination, valid)
    assert caught.value.code == "REACTION_PATH_WRITE_FAILED"
    assert destination.read_text(encoding="utf-8") == '{"existing": true}\n'
    assert not (tmp_path / "reaction-path.json.tmp").exists()


def test_source_metadata_cannot_escape_job_directory(tmp_path):
    with pytest.raises(ReactionPathError) as caught:
        ReactionPathManifestGenerator._metadata_source_path(tmp_path, "../escape.xyz")
    assert caught.value.code == "PATH_OUTSIDE_JOB"
