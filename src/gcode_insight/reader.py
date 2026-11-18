"""File access: plain G-code text and Bambu/Orca ``.gcode.3mf`` archives."""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterator
from pathlib import Path

__all__ = ["list_plates", "read_gcode_lines"]

_PLATE_NAME = re.compile(r"^Metadata/plate_(\d+)\.gcode$")


def list_plates(path: str | Path) -> list[int]:
    """Plate numbers that have G-code inside a ``.gcode.3mf`` archive."""
    with zipfile.ZipFile(path) as archive:
        return sorted(_plates(archive))


def _plates(archive: zipfile.ZipFile) -> dict[int, str]:
    plates: dict[int, str] = {}
    for name in archive.namelist():
        match = _PLATE_NAME.match(name)
        if match is not None:
            plates[int(match.group(1))] = name
    return plates


def read_gcode_lines(path: str | Path, plate: int | None = None) -> Iterator[str]:
    """Yield the text lines of a G-code file without loading it whole.

    ``path`` may be a plain text file or a ``.gcode.3mf`` zip archive as exported
    by Bambu Studio / OrcaSlicer, in which case ``plate`` selects
    ``Metadata/plate_<n>.gcode`` (default: the lowest-numbered plate present).
    Undecodable bytes are replaced rather than raising.
    """
    path = Path(path)
    if not zipfile.is_zipfile(path):
        if plate is not None:
            raise ValueError(f"{path.name} is not a .3mf archive; --plate does not apply")
        with path.open("r", encoding="utf-8", errors="replace", newline=None) as handle:
            yield from handle
        return

    with zipfile.ZipFile(path) as archive:
        plates = _plates(archive)
        if not plates:
            raise ValueError(f"{path.name} contains no sliced G-code (Metadata/plate_N.gcode)")
        number = min(plates) if plate is None else plate
        if number not in plates:
            available = ", ".join(str(n) for n in sorted(plates))
            raise ValueError(f"plate {number} not found in {path.name}; available: {available}")
        with (
            archive.open(plates[number]) as raw,
            io.TextIOWrapper(raw, encoding="utf-8", errors="replace") as text,
        ):
            yield from text
