from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from backend.app.reaction_path.geometry import (
    align_path,
    create_display_frames,
    image_coordinates,
    mass_weighted_kabsch,
)
from backend.app.reaction_path.orbitals import (
    GridOrbitalOverlapProvider,
    OrbitalTracker,
    align_phase,
    common_grid,
    match_orbitals,
    maximum_weight_assignment,
    interpolate_scalar_fields,
)
from backend.app.reaction_path.service import EV_TO_HARTREE, ReactionPathError, ReactionPathService
from backend.app.surfaces.cube import CubeData


FIXTURE = Path(__file__).parent / "fixtures" / "reaction-path.json"


class FakeJobs:
    def __init__(self, directory: Path):
        self.directory = directory

    def _job_dir(self, _job_id):
        return self.directory


def load_fixture(directory: Path) -> dict:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    (directory / "reaction-path.json").write_text(json.dumps(raw), encoding="utf-8")
    return raw


def test_manifest_parses_converts_energy_and_keeps_calculated_images_immutable(tmp_path):
    raw = load_fixture(tmp_path)
    playback = ReactionPathService(FakeJobs(tmp_path)).load(uuid4())
    assert playback.path.images[0].energy_hartree == pytest.approx(raw["images"][0]["energy"] * EV_TO_HARTREE)
    assert playback.path.images[1].relative_energy_kj_mol > 0
    assert len(playback.display_frames) == 17
    with pytest.raises(Exception):
        playback.path.images[0].energy_hartree = 0


@pytest.mark.parametrize("mutation, code", [
    (lambda raw: raw["images"][1]["atoms"].pop(), "ATOM_COUNT_MISMATCH"),
    (lambda raw: raw["images"][1]["atoms"][0].update(element="C"), "ELEMENT_ORDER_MISMATCH"),
    (lambda raw: raw["images"][1]["atoms"].reverse(), "ATOM_ORDER_MISMATCH"),
])
def test_manifest_rejects_atom_mismatch(tmp_path, mutation, code):
    raw = load_fixture(tmp_path)
    mutation(raw)
    (tmp_path / "reaction-path.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ReactionPathError, match="계산 지점") as caught:
        ReactionPathService(FakeJobs(tmp_path)).load(uuid4())
    assert caught.value.code == code


def test_manifest_requires_energy_unit_and_contains_references(tmp_path):
    raw = load_fixture(tmp_path)
    raw.pop("energyUnit")
    (tmp_path / "reaction-path.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ReactionPathError) as caught:
        ReactionPathService(FakeJobs(tmp_path)).load(uuid4())
    assert caught.value.code == "ENERGY_UNIT_REQUIRED"
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["images"][0]["wavefunctionRef"] = "../escape.gbw"
    (tmp_path / "reaction-path.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ReactionPathError) as caught:
        ReactionPathService(FakeJobs(tmp_path)).load(uuid4())
    assert caught.value.code == "PATH_OUTSIDE_JOB"


def test_mass_weighted_kabsch_removes_rigid_rotation_and_translation():
    reference = np.asarray([[0, 0, 0], [1, 0, 0], [0, 2, 0]], dtype=float)
    rotation = np.asarray([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=float)
    moving = reference @ rotation + np.asarray([3, -2, 4])
    aligned = mass_weighted_kabsch(reference, moving, ["O", "H", "H"])
    assert np.allclose(aligned, reference, atol=1e-10)


def test_display_frames_preserve_endpoints_and_source_images(tmp_path):
    playback = ReactionPathService(FakeJobs(tmp_path))._parse(tmp_path, json.loads(FIXTURE.read_text(encoding="utf-8")))
    source = [image_coordinates(image).copy() for image in playback.path.images]
    aligned = align_path(playback.path.images, playback.path.elements)
    frames = create_display_frames(playback.path.images, playback.path.elements, samples_per_segment=4)
    assert np.array_equal(frames[0].coordinates, aligned[0])
    assert np.array_equal(frames[-1].coordinates, aligned[-1])
    assert [frame.is_calculated for frame in frames] == [True, False, False, False, True, False, False, False, True]
    assert all(np.array_equal(before, image_coordinates(after)) for before, after in zip(source, playback.path.images, strict=True))


def test_two_image_path_uses_linear_interpolation(tmp_path):
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["images"] = raw["images"][:2]
    playback = ReactionPathService(FakeJobs(tmp_path))._parse(tmp_path, raw)
    frame = create_display_frames(playback.path.images, playback.path.elements, samples_per_segment=2)[1]
    aligned = align_path(playback.path.images, playback.path.elements)
    assert np.allclose(frame.coordinates, (aligned[0] + aligned[1]) / 2)


def cube(values, origin=(0, 0, 0), spacing=1.0):
    array = np.asarray(values, dtype=float)
    return CubeData(np.asarray(origin, dtype=float), np.eye(3) * spacing, array.shape, array)


def test_common_grid_signed_overlap_and_phase_alignment():
    left = cube(np.arange(8).reshape(2, 2, 2) - 3.5)
    right = cube(-(np.arange(8).reshape(2, 2, 2) - 3.5))
    grid = common_grid([left, right], padding=0)
    assert grid.shape == (2, 2, 2)
    overlap = GridOrbitalOverlapProvider().compute_signed_overlap(left, right)
    assert overlap == pytest.approx(-1)
    assert np.array_equal(align_phase(right.values, overlap), left.values)
    assert np.array_equal(right.values, -left.values)
    assert np.allclose(interpolate_scalar_fields(left.values, align_phase(right.values, overlap), 0.5), left.values)


def test_overlap_threshold_assignment_and_terminal_tracking():
    at_threshold = match_orbitals(["a"], ["b"], np.asarray([[0.60]]))[0]
    below = match_orbitals(["a"], ["b"], np.asarray([[0.5999]]))[0]
    assert at_threshold.status == "matched"
    assert below.status == "below-threshold" and below.right_orbital_id is None
    assert set(maximum_weight_assignment(np.asarray([[0.8, 0.9], [0.7, 0.1]]))) == {(0, 1), (1, 0)}
    ambiguous = match_orbitals(["a"], ["b", "c"], np.asarray([[0.81, 0.80]]))[0]
    assert ambiguous.status == "ambiguous" and ambiguous.right_orbital_id == "b"
    tracker = OrbitalTracker("a")
    assert tracker.advance("b", 0.59).status == "below-threshold"
    assert tracker.advance("c", 0.99).status == "below-threshold"
