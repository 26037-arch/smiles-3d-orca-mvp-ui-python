from __future__ import annotations

from typing import Iterator


def install_opi_utf8_compatibility() -> None:
    """Make OPI 2.0 ORCA-output searches independent of the Windows locale.

    OPI 2.0's ``Grepper`` opens ``.out`` files without an encoding. On Korean
    Windows that means CP949, while ORCA 6.1 writes UTF-8 punctuation in its
    citation section. Keep the workaround local to OPI instead of changing
    Python's global ``open`` behavior.
    """
    try:
        from opi.output.grepper.core import Grepper
    except ImportError:
        return

    if getattr(Grepper.open_file, "_geoorca_utf8", False):
        return

    def open_file_utf8(self: object) -> Iterator[str]:
        return self.file.open(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    open_file_utf8._geoorca_utf8 = True  # type: ignore[attr-defined]
    Grepper.open_file = open_file_utf8
