"""Streaming G-code tokenizer.

The parser turns text lines into :class:`Command` objects one at a time, so a
multi-hundred-megabyte file never has to be held in memory. It is deliberately
tolerant: anything it does not understand is still returned (with whatever
words could be extracted) and the analyser decides what to ignore.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

__all__ = ["Command", "iter_commands", "parse_line"]

_LINE_NUMBER = re.compile(r"^[Nn]\d+\s*")
_CHECKSUM = re.compile(r"\*\d+\s*$")
_HEAD = re.compile(r"^([GgMmTt])\s*(\d+)(?:\.(\d+))?")
_WORD = re.compile(r"([A-Za-z])\s*([-+]?(?:\d+\.?\d*|\.\d+))?")

# Commands whose arguments are free text rather than letter/number words.
_TEXT_COMMANDS = frozenset({"M23", "M28", "M30", "M32", "M117", "M118", "M1002"})


@dataclass(frozen=True, slots=True)
class Command:
    """One parsed G-code line.

    Attributes:
        line_no: 1-based line number in the source.
        code: Normalised command word such as ``"G1"``, ``"M104"`` or ``"T0"``.
            Leading zeros are dropped (``G01`` becomes ``G1``); sub-codes are kept
            (``G38.2``). Empty for comment-only lines. Non-standard commands
            (for example Klipper's ``SET_VELOCITY_LIMIT``) are upper-cased as is.
        params: Letter -> numeric value, e.g. ``{"X": 10.0, "E": 0.5}``.
        flags: Letters that appeared without a value (``G28 X Y``).
        comment: Text after the first ``;`` with surrounding whitespace removed,
            or ``None`` when the line has no comment.
    """

    line_no: int
    code: str
    params: dict[str, float] = field(default_factory=dict)
    flags: frozenset[str] = frozenset()
    comment: str | None = None


def parse_line(line: str, line_no: int = 0) -> Command | None:
    """Parse one line. Returns ``None`` for blank lines."""
    body, sep, comment_text = line.partition(";")
    comment = comment_text.strip() if sep else None
    body = body.strip()
    if not body:
        if comment is None:
            return None
        return Command(line_no=line_no, code="", comment=comment)

    body = _LINE_NUMBER.sub("", body)
    body = _CHECKSUM.sub("", body).strip()
    if not body:
        return Command(line_no=line_no, code="", comment=comment)

    head = _HEAD.match(body)
    if head is None:
        # Not a classic letter+number command (Klipper macro or similar).
        return Command(line_no=line_no, code=body.split()[0].upper(), comment=comment)

    letter, number, sub = head.groups()
    code = f"{letter.upper()}{int(number)}"
    if sub is not None:
        code = f"{code}.{sub}"
    if code in _TEXT_COMMANDS:
        return Command(line_no=line_no, code=code, comment=comment)

    params: dict[str, float] = {}
    flags: set[str] = set()
    for word, value in _WORD.findall(body[head.end() :]):
        key = word.upper()
        if value:
            params[key] = float(value)
        else:
            flags.add(key)
    return Command(
        line_no=line_no,
        code=code,
        params=params,
        flags=frozenset(flags - params.keys()),
        comment=comment,
    )


def iter_commands(lines: Iterable[str]) -> Iterator[Command]:
    """Yield a :class:`Command` for every non-blank line of ``lines``."""
    for line_no, line in enumerate(lines, start=1):
        command = parse_line(line, line_no)
        if command is not None:
            yield command
