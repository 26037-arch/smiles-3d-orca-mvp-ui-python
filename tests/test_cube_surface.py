from __future__ import annotations


import numpy as np
import pytest

from backend.app.surfaces.cube import BOHR_TO_ANGSTROM, CubeData, CubeError, read_cube
from backend.app.surfaces.mesh import cache_key, contour_to_ply, demo_surface_ply


def cube_text(sign=1):
    return "\n".join(
        [
            "test cube",
            "generated",
            "1 1.0 2.0 3.0",
            f"{2 * sign} 1.0 0.0 0.0",
            f"{2 * sign} 0.0 1.0 0.0",
            f"{2 * sign} 0.0 0.0 1.0",
            "1 0 0 0 0",
            "-1.0 -0.5 0.5 1.0  -1.0 -0.5 0.5 1.0",
            "",
        ]
    )


def test_cube_bohr_coordinate_conversion(tmp_path):
    path = tmp_path / "field.cube"
    path.write_text(cube_text(1), encoding="utf-8")
    cube = read_cube(path)
    assert cube.shape == (2, 2, 2)
    assert np.allclose(cube.origin, np.array([1, 2, 3]) * BOHR_TO_ANGSTROM)
    assert np.allclose(cube.axes[0], [BOHR_TO_ANGSTROM, 0, 0])


def test_cube_negative_counts_mean_angstrom(tmp_path):
    path = tmp_path / "field.cube"
    path.write_text(cube_text(-1), encoding="utf-8")
    cube = read_cube(path)
    assert np.allclose(cube.origin, [1, 2, 3])


def test_negative_natoms_skips_orca_dataset_ids(tmp_path):
    path = tmp_path / "mo.cube"
    path.write_text(
        "\n".join(
            [
                "ORCA cube",
                "Molecular orbital 5",
                "-2 0.0 0.0 0.0",
                "2 1.0 0.0 0.0",
                "2 0.0 1.0 0.0",
                "2 0.0 0.0 1.0",
                "7 7.0 0.0 0.0 0.0",
                "7 7.0 1.0 0.0 0.0",
                "1 5",
                "-1.0 -0.5 0.0 0.5 1.0 1.5 2.0 2.5",
            ]
        ),
        encoding="ascii",
    )

    cube = read_cube(path)

    assert cube.values.shape == (2, 2, 2)
    assert cube.values.ravel(order="C").tolist() == [
        -1.0,
        -0.5,
        0.0,
        0.5,
        1.0,
        1.5,
        2.0,
        2.5,
    ]


def test_cube_rejects_extra_or_missing_scalars(tmp_path):
    path = tmp_path / "bad-count.cube"
    path.write_text(
        cube_text(1).replace(
            "-1.0 -0.5 0.5 1.0  -1.0 -0.5 0.5 1.0",
            "-1.0 -0.5 0.5 1.0  -1.0 -0.5 0.5 1.0 99.0",
        ),
        encoding="ascii",
    )

    with pytest.raises(CubeError, match="scalar count mismatch"):
        read_cube(path)


def test_cube_rejects_multiple_interleaved_datasets(tmp_path):
    path = tmp_path / "multiple-mo.cube"
    path.write_text(
        "\n".join(
            [
                "cube",
                "multiple orbitals",
                "-1 0.0 0.0 0.0",
                "1 1.0 0.0 0.0",
                "1 0.0 1.0 0.0",
                "1 0.0 0.0 1.0",
                "1 1.0 0.0 0.0 0.0",
                "2",
                "4 5",
                "0.1 0.2",
            ]
        ),
        encoding="ascii",
    )

    with pytest.raises(CubeError, match="2 interleaved datasets"):
        read_cube(path)


def test_corrupt_cube_is_structured_error(tmp_path):
    path = tmp_path / "broken.cube"
    path.write_text("bad", encoding="utf-8")
    with pytest.raises(CubeError):
        read_cube(path)


def test_mesh_cache_key_excludes_opacity_and_separates_phase():
    a = cache_key("abc", "mo", 3, "alpha", "positive", 0.03)
    assert a == cache_key("abc", "mo", 3, "alpha", "positive", 0.03)
    assert a != cache_key("abc", "mo", 3, "alpha", "negative", 0.03)
    assert a != cache_key("abc", "mo", 3, "alpha", "positive", 0.04)


def test_demo_positive_and_negative_meshes(tmp_path):
    positive = tmp_path / "p.ply"
    negative = tmp_path / "n.ply"
    demo_surface_ply(positive, field="mo", sign=1, orbital=2)
    demo_surface_ply(negative, field="mo", sign=-1, orbital=2)
    assert positive.read_bytes() != negative.read_bytes()
    assert b"element face" in positive.read_bytes()


def test_pyvista_extracts_positive_and_negative_mo_contours(tmp_path):
    shape = (17, 17, 17)
    x, y, z = np.meshgrid(*(np.linspace(-1, 1, n) for n in shape), indexing="ij")
    values = x * np.exp(-4 * (x * x + y * y + z * z))
    cube = CubeData(
        origin=np.array([-1.0, -1.0, -1.0]),
        axes=np.diag([2 / 16, 2 / 16, 2 / 16]),
        shape=shape,
        values=values,
    )
    positive = tmp_path / "positive.ply"
    negative = tmp_path / "negative.ply"
    contour_to_ply(cube, 0.08, positive)
    contour_to_ply(cube, -0.08, negative)
    assert positive.stat().st_size > 100
    assert negative.stat().st_size > 100


def test_contour_rejects_isovalue_that_reaches_cube_boundary(tmp_path):
    shape = (9, 9, 9)
    values = np.zeros(shape)
    values[0, 4, 4] = 0.02
    cube = CubeData(
        origin=np.zeros(3),
        axes=np.eye(3),
        shape=shape,
        values=values,
    )

    with pytest.raises(ValueError, match="reaches the Cube grid boundary"):
        contour_to_ply(cube, 0.01, tmp_path / "boundary.ply")
