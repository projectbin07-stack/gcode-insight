from __future__ import annotations

from gcode_insight.parser import iter_commands, parse_line


def test_basic_move_words() -> None:
    cmd = parse_line("G1 X10.5 Y-3 E.25 F1800", 7)
    assert cmd is not None
    assert cmd.line_no == 7
    assert cmd.code == "G1"
    assert cmd.params == {"X": 10.5, "Y": -3.0, "E": 0.25, "F": 1800.0}
    assert cmd.comment is None


def test_comment_is_preserved_and_stripped() -> None:
    cmd = parse_line("M104 S220 ; set nozzle temp ")
    assert cmd is not None
    assert cmd.code == "M104"
    assert cmd.params == {"S": 220.0}
    assert cmd.comment == "set nozzle temp"


def test_comment_only_line_keeps_inner_semicolons() -> None:
    cmd = parse_line("; model printing time: 11m 8s; total estimated time: 17m 22s")
    assert cmd is not None
    assert cmd.code == ""
    assert cmd.comment == "model printing time: 11m 8s; total estimated time: 17m 22s"


def test_blank_lines_are_skipped() -> None:
    assert parse_line("") is None
    assert parse_line("   \t\n") is None
    assert [c.code for c in iter_commands(["G28\n", "\n", ";x\n", "G1 X1\n"])] == ["G28", "", "G1"]
    assert [c.line_no for c in iter_commands(["G28\n", "\n", "G1 X1\n"])] == [1, 3]


def test_line_number_and_checksum_are_removed() -> None:
    cmd = parse_line("N42 G1 X5 Y6*71")
    assert cmd is not None
    assert cmd.code == "G1"
    assert cmd.params == {"X": 5.0, "Y": 6.0}


def test_case_leading_zeros_and_missing_spaces() -> None:
    cmd = parse_line("g01x10y5e0.4")
    assert cmd is not None
    assert cmd.code == "G1"
    assert cmd.params == {"X": 10.0, "Y": 5.0, "E": 0.4}


def test_subcode_is_kept() -> None:
    cmd = parse_line("G38.2 Z-5")
    assert cmd is not None
    assert cmd.code == "G38.2"
    assert cmd.params == {"Z": -5.0}


def test_valueless_words_become_flags() -> None:
    cmd = parse_line("G28 X Y")
    assert cmd is not None
    assert cmd.params == {}
    assert cmd.flags == frozenset({"X", "Y"})


def test_tool_change() -> None:
    cmd = parse_line("T1")
    assert cmd is not None
    assert cmd.code == "T1"


def test_text_commands_are_not_tokenised() -> None:
    cmd = parse_line("M117 Printing layer X1 of E5")
    assert cmd is not None
    assert cmd.code == "M117"
    assert cmd.params == {}
    assert cmd.flags == frozenset()


def test_klipper_style_command_is_passed_through() -> None:
    cmd = parse_line("SET_VELOCITY_LIMIT ACCEL=5000 ; klipper")
    assert cmd is not None
    assert cmd.code == "SET_VELOCITY_LIMIT"
    assert cmd.params == {}
    assert cmd.comment == "klipper"


def test_line_with_only_a_line_number() -> None:
    cmd = parse_line("N10 ; nothing here")
    assert cmd is not None
    assert cmd.code == ""
    assert cmd.comment == "nothing here"
