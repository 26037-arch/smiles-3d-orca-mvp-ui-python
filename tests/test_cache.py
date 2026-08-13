from __future__ import annotations

from backend.app.cache import BoundedLRU, DerivedCacheManager
from backend.app.config import LocalSettings


def write(path, size: int = 4):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_bounded_lru_evicts_by_entry_and_byte_size():
    cache = BoundedLRU[str, bytes](3, max_bytes=6, size_of=len)
    cache["a"] = b"aa"
    cache["b"] = b"bb"
    _ = cache["a"]
    cache["c"] = b"cccc"
    assert list(cache) == ["a", "c"]
    cache["d"] = b"d"
    cache["e"] = b"e"
    assert list(cache) == ["c", "d", "e"]


def test_disk_cache_evicts_tracking_then_mesh_then_cube_and_keeps_gbw(tmp_path):
    settings = LocalSettings(
        jobs_dir=str(tmp_path),
        max_mesh_cache_entries=2,
        max_cube_cache_entries=2,
        max_derived_cache_bytes=10,
    )
    cache = DerivedCacheManager(settings)
    job = tmp_path / "job"
    tracking_old = write(job / "cache" / "tracking" / "old.ply")
    tracking_current = write(job / "cache" / "tracking" / "current.ply")
    mesh = write(job / "cache" / "meshes" / "surface.ply")
    cube_old = write(job / "cache" / "cubes" / "old.cube")
    cube_current = write(job / "cache" / "cubes" / "current.cube")
    gbw = write(job / "step-000.gbw", 100)

    cache.record(tracking_current, protected=[cube_current])

    assert not tracking_old.exists()
    assert tracking_current.exists()
    assert not mesh.exists()
    assert not cube_old.exists()
    assert cube_current.exists()
    assert gbw.exists()


def test_disk_cache_count_limit_never_evicts_current_mesh(tmp_path):
    settings = LocalSettings(
        jobs_dir=str(tmp_path), max_mesh_cache_entries=1, max_derived_cache_bytes=100
    )
    cache = DerivedCacheManager(settings)
    job = tmp_path / "job"
    old = write(job / "cache" / "meshes" / "old.ply")
    current = write(job / "cache" / "meshes" / "current.ply")

    cache.record(current)

    assert not old.exists()
    assert current.exists()


def test_tracking_metadata_cache_is_bounded(tmp_path):
    settings = LocalSettings(
        jobs_dir=str(tmp_path),
        max_tracking_cache_entries=1,
        max_derived_cache_bytes=100,
    )
    cache = DerivedCacheManager(settings)
    job = tmp_path / "job"
    old = write(job / "cache" / "tracking" / "old.json")
    current = write(job / "cache" / "tracking" / "current.json")

    cache.record(current)

    assert not old.exists()
    assert current.exists()
