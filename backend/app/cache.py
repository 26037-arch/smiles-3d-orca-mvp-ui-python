from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator, MutableMapping
from pathlib import Path
from typing import Generic, TypeVar

from .config import LocalSettings


K = TypeVar("K")
V = TypeVar("V")


class BoundedLRU(MutableMapping[K, V], Generic[K, V]):
    """Small thread-safe LRU used for parsed Cube arrays and overlap scalars."""

    def __init__(
        self,
        max_entries: int,
        *,
        max_bytes: int | None = None,
        size_of: Callable[[V], int] | None = None,
    ) -> None:
        self.max_entries = max(1, max_entries)
        self.max_bytes = max_bytes
        self.size_of = size_of or (lambda _value: 1)
        self._items: OrderedDict[K, V] = OrderedDict()
        self._bytes = 0
        self._lock = threading.RLock()

    def __getitem__(self, key: K) -> V:
        with self._lock:
            value = self._items.pop(key)
            self._items[key] = value
            return value

    def __setitem__(self, key: K, value: V) -> None:
        with self._lock:
            previous = self._items.pop(key, None)
            if previous is not None:
                self._bytes -= self.size_of(previous)
            self._items[key] = value
            self._bytes += self.size_of(value)
            while len(self._items) > self.max_entries or (
                self.max_bytes is not None and self._bytes > self.max_bytes
            ):
                _, removed = self._items.popitem(last=False)
                self._bytes -= self.size_of(removed)

    def __delitem__(self, key: K) -> None:
        with self._lock:
            value = self._items.pop(key)
            self._bytes -= self.size_of(value)

    def __iter__(self) -> Iterator[K]:
        with self._lock:
            return iter(tuple(self._items))

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


class DerivedCacheManager:
    """Owns only reproducible Cube/PLY artifacts; persistent GBW files are never candidates."""

    _CATEGORY_DIR = {
        "cube": "cubes",
        "mesh": "meshes",
        "tracking": "tracking",
    }

    def __init__(self, settings: LocalSettings):
        self.settings = settings
        self._accessed: dict[Path, int] = {}
        self._pinned: set[Path] = set()
        self._lock = threading.RLock()

    def pin(self, path: Path) -> Path:
        resolved = path.resolve()
        with self._lock:
            self._pinned.add(resolved)
        return resolved

    def unpin(self, path: Path) -> Path:
        resolved = path.resolve()
        with self._lock:
            self._pinned.discard(resolved)
        return resolved

    def directory(self, job_dir: Path, category: str) -> Path:
        directory = job_dir / "cache" / self._CATEGORY_DIR[category]
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def record(self, path: Path, *, protected: Iterable[Path] = ()) -> list[Path]:
        path = path.resolve()
        with self._lock:
            self._accessed[path] = time.monotonic_ns()
            return self.enforce(path.parents[2], protected={path, *protected})

    def enforce(self, job_dir: Path, *, protected: Iterable[Path] = ()) -> list[Path]:
        job_dir = job_dir.resolve()
        protected_paths = {path.resolve() for path in protected}
        with self._lock:
            protected_paths |= self._pinned
            entries = self._entries(job_dir)
            removed: list[Path] = []

            meshes = [entry for entry in entries if entry[0] in {"tracking", "mesh"}]
            cubes = [entry for entry in entries if entry[0] == "cube"]
            metadata = [entry for entry in entries if entry[0] == "metadata"]
            self._trim_count(
                meshes,
                self.settings.max_mesh_cache_entries,
                protected_paths,
                removed,
            )
            self._trim_count(
                cubes,
                self.settings.max_cube_cache_entries,
                protected_paths,
                removed,
            )
            self._trim_count(
                metadata,
                self.settings.max_tracking_cache_entries,
                protected_paths,
                removed,
            )

            remaining = [entry for entry in self._entries(job_dir) if entry[1] not in removed]
            total = sum(entry[3] for entry in remaining)
            if total > self.settings.max_derived_cache_bytes:
                # Preserve the requested eviction order even when an older Cube exists.
                for category in ("tracking", "mesh", "cube", "metadata"):
                    candidates = sorted(
                        (entry for entry in remaining if entry[0] == category),
                        key=lambda entry: entry[2],
                    )
                    for _, path, _, size in candidates:
                        if total <= self.settings.max_derived_cache_bytes:
                            break
                        if path in protected_paths:
                            continue
                        if self._remove(path):
                            removed.append(path)
                            total -= size
                    if total <= self.settings.max_derived_cache_bytes:
                        break
            return removed

    def _trim_count(
        self,
        entries: list[tuple[str, Path, int, int]],
        maximum: int,
        protected: set[Path],
        removed: list[Path],
    ) -> None:
        excess = max(0, len(entries) - maximum)
        if not excess:
            return
        # Tracking animation meshes are always evicted before ordinary surfaces.
        ordered = sorted(entries, key=lambda entry: (entry[0] != "tracking", entry[2]))
        for _, path, _, _ in ordered:
            if excess <= 0:
                break
            if path in protected:
                continue
            if self._remove(path):
                removed.append(path)
                excess -= 1

    def _entries(self, job_dir: Path) -> list[tuple[str, Path, int, int]]:
        patterns = (
            ("tracking", job_dir / "cache" / "tracking", "*.ply"),
            ("metadata", job_dir / "cache" / "tracking", "*.json"),
            ("tracking", job_dir / "reaction-surfaces", "*.ply"),
            ("mesh", job_dir / "cache" / "meshes", "*.ply"),
            ("mesh", job_dir / "surfaces", "*.ply"),
            ("cube", job_dir / "cache" / "cubes", "*.cube"),
            ("cube", job_dir / "fields", "*.cube"),
            ("cube", job_dir / "ao-cubes", "*.cube"),
        )
        entries: list[tuple[str, Path, int, int]] = []
        seen: set[Path] = set()
        for category, directory, pattern in patterns:
            if not directory.is_dir():
                continue
            for candidate in directory.glob(pattern):
                path = candidate.resolve()
                if path in seen or not path.is_file():
                    continue
                seen.add(path)
                try:
                    stat = path.stat()
                except OSError:
                    continue
                last_used = self._accessed.get(path, stat.st_mtime_ns)
                entries.append((category, path, last_used, stat.st_size))
        return entries

    def _remove(self, path: Path) -> bool:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        self._accessed.pop(path, None)
        return True
