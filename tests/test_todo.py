from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from todo import app
from todo.app import Item, TodoError, TodoList, escape_text, format_item, parse_id
from todo.cli import build_parser, main

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def path(tmp_path: Path) -> Path:
    return tmp_path / "todo.json"


def write_store(path: Path, items: list[dict], next_id: int | None = None, version: int = 1) -> None:
    if next_id is None:
        next_id = max((i["id"] for i in items), default=0) + 1
    path.write_text(json.dumps({"version": version, "next_id": next_id, "items": items}), encoding="utf-8")


def run(path: Path, *argv: str) -> int:
    return main(["--file", str(path), *argv])


# Task 1: data model and standard library only -------------------------------------------------


def test_item_status_values() -> None:
    assert Item(id=1, title="a").status == "open"
    assert Item(id=1, title="a", status="done").status == "done"
    assert app.STATUSES == ("open", "done")


def test_module_uses_only_standard_library() -> None:
    for name in ("app.py", "cli.py"):
        tree = ast.parse((ROOT / "todo" / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module.split(".")[0]]
            for module in modules:
                assert module in sys.stdlib_module_names or module == "todo", (name, module)


# Task 2: loading and validation ---------------------------------------------------------------


def test_missing_file_gives_empty_list_and_creates_nothing(path: Path) -> None:
    assert TodoList(path).list() == []
    assert not path.exists()


def test_empty_zero_byte_file_is_reported(path: Path) -> None:
    path.write_bytes(b"")
    with pytest.raises(TodoError):
        TodoList(path)
    assert path.read_bytes() == b""


GOOD = {"id": 1, "title": "a", "status": "open"}
CORRUPT = [
    b"not json",
    b"\xff\xfe\x00bad utf8",
    b"[]",
    b"{}",
    json.dumps({"version": 1, "next_id": 2, "items": 5}).encode(),
    json.dumps({"version": 1, "next_id": 2, "items": [5]}).encode(),
    json.dumps({"version": 1, "next_id": 2, "items": [{"id": 1, "title": "a"}]}).encode(),
    json.dumps({"version": 1, "next_id": 2, "items": [{"id": "1", "title": "a", "status": "open"}]}).encode(),
    json.dumps({"version": 1, "next_id": 2, "items": [{"id": 1, "title": 7, "status": "open"}]}).encode(),
    json.dumps({"version": 1, "next_id": 2, "items": [{"id": True, "title": "a", "status": "open"}]}).encode(),
    json.dumps({"version": 1, "next_id": True, "items": []}).encode(),
    json.dumps({"version": 1, "next_id": 3, "items": [GOOD, GOOD]}).encode(),
    json.dumps({"version": 1, "next_id": 2, "items": [{"id": 0, "title": "a", "status": "open"}]}).encode(),
    json.dumps({"version": 1, "next_id": 2, "items": [{"id": -1, "title": "a", "status": "open"}]}).encode(),
    json.dumps({"version": 1, "next_id": 2, "items": [{"id": 1, "title": "a", "status": "finished"}]}).encode(),
    json.dumps({"version": 1, "next_id": 1, "items": [GOOD]}).encode(),
    json.dumps({"version": 1, "next_id": 0, "items": []}).encode(),
    json.dumps({"version": 2, "next_id": 2, "items": [GOOD]}).encode(),
    json.dumps({"version": True, "next_id": 2, "items": [GOOD]}).encode(),
    json.dumps({"next_id": 2, "items": [GOOD]}).encode(),
]


@pytest.mark.parametrize("content", CORRUPT)
def test_corrupt_file_is_reported_not_overwritten(path: Path, content: bytes) -> None:
    path.write_bytes(content)
    with pytest.raises(TodoError, match="cannot read"):
        TodoList(path)
    assert path.read_bytes() == content


def test_old_sample_format_is_rejected_with_advice(path: Path) -> None:
    path.write_text(json.dumps({"items": [{"id": 1, "title": "a", "done": False}]}), encoding="utf-8")
    with pytest.raises(TodoError, match="old file format"):
        TodoList(path)


def test_path_that_is_a_directory_is_reported(tmp_path: Path) -> None:
    with pytest.raises(TodoError, match="cannot read"):
        TodoList(tmp_path)


def test_valid_file_loads(path: Path) -> None:
    write_store(path, [GOOD, {"id": 3, "title": "b", "status": "done"}], next_id=5)
    todos = TodoList(path)
    assert [(i.id, i.title, i.status) for i in todos.list()] == [(1, "a", "open"), (3, "b", "done")]
    assert todos.next_id == 5


# Task 3: atomic save --------------------------------------------------------------------------


def test_save_leaves_no_temp_files(path: Path) -> None:
    TodoList(path).add("a")
    assert [p.name for p in path.parent.iterdir()] == ["todo.json"]


def test_save_creates_missing_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "todo.json"
    TodoList(target).add("a")
    assert target.exists()


def test_saved_file_uses_documented_format(path: Path) -> None:
    TodoList(path).add("Buy milk")
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 1,
        "next_id": 2,
        "items": [{"id": 1, "title": "Buy milk", "status": "open"}],
    }


def test_failed_replace_keeps_old_file_and_removes_temp(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    todos = TodoList(path)
    todos.add("a")
    before = path.read_bytes()

    def boom(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(TodoError, match="cannot write"):
        todos.add("b")
    assert path.read_bytes() == before
    assert [p.name for p in path.parent.iterdir()] == ["todo.json"]
    assert [i.title for i in todos.list()] == ["a"]
    assert todos.next_id == 2


# Task 4: escaping -----------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["Buy milk", "  spaced   out  ", "a, b; c! (d)?", "caf\u00e9 \u65e5\u672c\u8a9e \U0001f600", ""])
def test_escape_keeps_printable_text(text: str) -> None:
    assert escape_text(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a\x1b[31mb", "a\\x1b[31mb"),
        ("a\nb", "a\\x0ab"),
        ("a\tb", "a\\x09b"),
        ("a\rb", "a\\x0db"),
        ("a\x00b", "a\\x00b"),
        ("a\u202eb", "a\\u202eb"),
        ("a\U000e0001b", "a\\U000e0001b"),
    ],
)
def test_escape_makes_controls_visible(text: str, expected: str) -> None:
    assert escape_text(text) == expected


# Task 5: id parsing ---------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "value"), [("1", 1), ("007", 7), ("999999999999999999", 999999999999999999)])
def test_parse_id_accepts_whole_numbers(text: str, value: int) -> None:
    assert parse_id(text) == value


@pytest.mark.parametrize(
    "text",
    ["abc", "1.5", "-3", "0", "", " ", "1 ", "1\n", "\u0661\u0662", "+1", "1e3", "0000", "1" * 19],
)
def test_parse_id_rejects_invalid_text(text: str) -> None:
    with pytest.raises(TodoError, match="invalid id"):
        parse_id(text)


def test_parse_id_rejects_5000_digit_text_without_value_error() -> None:
    with pytest.raises(TodoError, match="invalid id"):
        parse_id("9" * 5000)


def test_parse_id_message_escapes_control_characters() -> None:
    with pytest.raises(TodoError) as info:
        parse_id("\x1b[31mred")
    assert "\x1b" not in str(info.value)
    assert "\\x1b" in str(info.value)


def test_parse_id_message_is_shortened_for_long_text() -> None:
    with pytest.raises(TodoError) as info:
        parse_id("x" * 5000)
    assert len(str(info.value)) < 200


# Task 6: add ----------------------------------------------------------------------------------


def test_add_creates_open_task_with_unique_id(path: Path) -> None:
    todos = TodoList(path)
    first = todos.add("Buy milk")
    second = todos.add("Pay rent")
    assert (first.id, first.title, first.status) == (1, "Buy milk", "open")
    assert second.id != first.id and second.status == "open"


def test_add_persists_across_reload(path: Path) -> None:
    todos = TodoList(path)
    todos.add("a")
    todos.add("b")
    assert [(i.id, i.title) for i in TodoList(path).list()] == [(1, "a"), (2, "b")]


def test_id_is_not_reused_after_deleting_newest_task(path: Path) -> None:
    todos = TodoList(path)
    todos.add("a")
    todos.add("b")
    todos.delete(2)
    assert todos.add("c").id == 3
    assert TodoList(path).add("d").id == 4


@pytest.mark.parametrize("title", ["  leading and trailing  ", "a   b", "!?;:'\"", "caf\u00e9 \u65e5\u672c\u8a9e", "x" * 10000, "-5 degrees"])
def test_title_is_stored_exactly(path: Path, title: str) -> None:
    todos = TodoList(path)
    assert todos.add(title).title == title
    assert TodoList(path).list()[0].title == title


@pytest.mark.parametrize("title", ["", "   ", "\t", "\n", " \t\n "])
def test_empty_and_whitespace_titles_are_rejected_without_writing(path: Path, title: str) -> None:
    todos = TodoList(path)
    with pytest.raises(TodoError, match="empty"):
        todos.add(title)
    assert not path.exists()
    assert todos.list() == [] and todos.next_id == 1


# Task 7: list ---------------------------------------------------------------------------------


def test_list_is_in_creation_order(path: Path) -> None:
    todos = TodoList(path)
    for title in ("A", "B", "C"):
        todos.add(title)
    assert [i.title for i in todos.list()] == ["A", "B", "C"]
    assert [i.title for i in TodoList(path).list()] == ["A", "B", "C"]


def test_list_of_empty_list_is_empty(path: Path) -> None:
    assert TodoList(path).list() == []


def test_list_returns_copies(path: Path) -> None:
    todos = TodoList(path)
    todos.add("a")
    todos.list()[0].status = "done"
    assert todos.list()[0].status == "open"
    assert TodoList(path).list()[0].status == "open"


def test_list_does_not_write(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_store(path, [GOOD])
    todos = TodoList(path)
    monkeypatch.setattr(TodoList, "_save", lambda *a, **k: pytest.fail("list must not write"))
    todos.list()


# Task 8: complete and reopen ------------------------------------------------------------------


def test_complete_open_task(path: Path) -> None:
    todos = TodoList(path)
    todos.add("a")
    item, changed = todos.complete(1)
    assert changed is True and item.status == "done"
    assert TodoList(path).list()[0].status == "done"


def test_complete_done_task_is_noop_and_does_not_write(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_store(path, [{"id": 1, "title": "a", "status": "done"}])
    todos = TodoList(path)
    before = path.read_bytes()
    monkeypatch.setattr(TodoList, "_save", lambda *a, **k: pytest.fail("no-op must not write"))
    item, changed = todos.complete(1)
    assert changed is False and item.status == "done"
    assert path.read_bytes() == before


def test_reopen_done_task(path: Path) -> None:
    write_store(path, [{"id": 1, "title": "a", "status": "done"}])
    todos = TodoList(path)
    item, changed = todos.reopen(1)
    assert changed is True and item.status == "open"
    assert TodoList(path).list()[0].status == "open"


def test_reopen_open_task_is_noop(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_store(path, [GOOD])
    todos = TodoList(path)
    monkeypatch.setattr(TodoList, "_save", lambda *a, **k: pytest.fail("no-op must not write"))
    item, changed = todos.reopen(1)
    assert changed is False and item.status == "open"


@pytest.mark.parametrize("method", ["complete", "reopen", "delete"])
def test_unknown_id_raises_and_changes_nothing(path: Path, method: str) -> None:
    write_store(path, [GOOD])
    todos = TodoList(path)
    before = path.read_bytes()
    with pytest.raises(TodoError, match="no task with id 999"):
        getattr(todos, method)(999)
    assert path.read_bytes() == before
    assert [i.id for i in todos.list()] == [1]


# Task 9: delete -------------------------------------------------------------------------------


def test_delete_removes_task(path: Path) -> None:
    todos = TodoList(path)
    todos.add("a")
    todos.add("b")
    assert todos.delete(1).title == "a"
    assert [i.title for i in todos.list()] == ["b"]
    assert [i.title for i in TodoList(path).list()] == ["b"]


def test_delete_keeps_next_id(path: Path) -> None:
    todos = TodoList(path)
    todos.add("a")
    todos.delete(1)
    assert todos.next_id == 2
    assert json.loads(path.read_text(encoding="utf-8"))["next_id"] == 2


# Task 10: display line ------------------------------------------------------------------------


def test_format_item_shows_id_status_title() -> None:
    assert format_item(Item(id=3, title="Buy milk", status="open")) == "3  open  Buy milk"
    assert format_item(Item(id=4, title="x", status="done")) == "4  done  x"


def test_format_item_keeps_non_ascii_title() -> None:
    assert format_item(Item(id=1, title="caf\u00e9 \u65e5\u672c")) == "1  open  caf\u00e9 \u65e5\u672c"


def test_format_item_escapes_control_characters() -> None:
    assert "\x1b" not in format_item(Item(id=1, title="a\x1bb"))


# Task 11: parser ------------------------------------------------------------------------------


def test_parser_defines_all_commands() -> None:
    parser = build_parser()
    for argv in (["add", "x"], ["list"], ["done", "1"], ["reopen", "1"], ["delete", "1"]):
        assert parser.parse_args(argv).command == argv[0]


def test_help_names_default_file_and_dash_rule(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        build_parser().parse_args(["--help"])
    assert info.value.code == 0
    out = capsys.readouterr().out
    assert "todo.json" in out and "--" in out and "dash" in out


@pytest.mark.parametrize("argv", [["remove", "1"], ["list", "--pending"], []])
def test_removed_or_missing_commands_exit_2(path: Path, argv: list[str]) -> None:
    with pytest.raises(SystemExit) as info:
        run(path, *argv)
    assert info.value.code == 2


# Task 12: command handlers --------------------------------------------------------------------


def test_cli_add_prints_id_title_and_status(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(path, "add", "Buy milk") == 0
    captured = capsys.readouterr()
    assert captured.out == "added task 1: open - Buy milk\n" and captured.err == ""


def test_cli_add_joins_words_with_single_spaces(path: Path) -> None:
    assert run(path, "add", "buy", "some", "milk") == 0
    assert TodoList(path).list()[0].title == "buy some milk"


def test_cli_list_order_and_columns(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for title in ("A", "B", "C"):
        run(path, "add", title)
    run(path, "done", "2")
    capsys.readouterr()
    assert run(path, "list") == 0
    assert capsys.readouterr().out.splitlines() == ["1  open  A", "2  done  B", "3  open  C"]


def test_cli_empty_list_message(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(path, "list") == 0
    assert capsys.readouterr().out == "no tasks yet\n"


def test_cli_done_and_noop_messages(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(path, "add", "Buy milk")
    capsys.readouterr()
    assert run(path, "done", "1") == 0
    assert capsys.readouterr().out == "task 1 is now done: Buy milk\n"
    assert run(path, "done", "1") == 0
    assert capsys.readouterr().out == "task 1 is already done: Buy milk\n"
    assert TodoList(path).list()[0].status == "done"


def test_cli_reopen_and_noop_messages(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(path, "add", "Buy milk")
    run(path, "done", "1")
    capsys.readouterr()
    assert run(path, "reopen", "1") == 0
    assert capsys.readouterr().out == "task 1 is now open: Buy milk\n"
    assert run(path, "reopen", "1") == 0
    assert capsys.readouterr().out == "task 1 is already open: Buy milk\n"
    assert TodoList(path).list()[0].status == "open"


def test_cli_delete_then_list(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(path, "add", "Buy milk")
    capsys.readouterr()
    assert run(path, "delete", "1") == 0
    assert capsys.readouterr().out == "deleted task 1: Buy milk\n"
    run(path, "list")
    assert capsys.readouterr().out == "no tasks yet\n"


@pytest.mark.parametrize("command", ["done", "reopen", "delete"])
def test_cli_unknown_id_exit_1_and_no_change(path: Path, capsys: pytest.CaptureFixture[str], command: str) -> None:
    run(path, "add", "a")
    before = path.read_bytes()
    capsys.readouterr()
    assert run(path, command, "999") == 1
    captured = capsys.readouterr()
    assert captured.err == "error: no task with id 999\n" and captured.out == ""
    assert path.read_bytes() == before


@pytest.mark.parametrize("command", ["done", "reopen", "delete"])
@pytest.mark.parametrize("bad", ["abc", "1.5", "0", "9" * 5000, "1\x1b[31m", ""])
def test_cli_invalid_id_exit_1_and_no_change(path: Path, capsys: pytest.CaptureFixture[str], command: str, bad: str) -> None:
    run(path, "add", "a")
    before = path.read_bytes()
    capsys.readouterr()
    assert run(path, command, bad) == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error: invalid id") and captured.out == ""
    assert "\x1b" not in captured.err and len(captured.err) < 200
    assert path.read_bytes() == before


def test_cli_title_with_spaces_punctuation_and_non_ascii_is_stored_exactly(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    title = "  caf\u00e9, \u65e5\u672c\u8a9e!  (2x)  "
    assert run(path, "add", title) == 0
    assert TodoList(path).list()[0].title == title
    capsys.readouterr()
    run(path, "list")
    assert capsys.readouterr().out == f"1  open  {title}\n"


@pytest.mark.parametrize("title", ["", "   "])
def test_cli_empty_title_exit_1(path: Path, capsys: pytest.CaptureFixture[str], title: str) -> None:
    assert run(path, "add", title) == 1
    assert "error: title must not be empty" in capsys.readouterr().err
    assert not path.exists()


def test_cli_errors_go_to_stderr_and_success_to_stdout(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(path, "add", "a")
    out = capsys.readouterr()
    assert out.out and not out.err
    run(path, "done", "x")
    out = capsys.readouterr()
    assert out.err and not out.out


def test_cli_title_with_control_character_is_escaped_on_output(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(path, "add", "a\x1b[31mb")
    run(path, "list")
    run(path, "done", "1")
    run(path, "reopen", "1")
    run(path, "delete", "1")
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\\x1b" in out
    assert TodoList(path).list() == []


# Task 13: dash-leading input ------------------------------------------------------------------


def test_cli_add_after_double_dash_stores_dash_title(path: Path) -> None:
    assert run(path, "add", "--", "-urgent", "task") == 0
    assert TodoList(path).list()[0].title == "-urgent task"


def test_cli_add_dash_title_without_double_dash_exits_2_and_adds_nothing(path: Path) -> None:
    with pytest.raises(SystemExit) as info:
        run(path, "add", "-urgent")
    assert info.value.code == 2
    assert not path.exists()


def test_cli_add_negative_number_title_is_accepted(path: Path) -> None:
    assert run(path, "add", "-5", "degrees") == 0
    assert TodoList(path).list()[0].title == "-5 degrees"


def test_cli_done_with_dash_id_after_double_dash_exits_1_with_invalid_id_message(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(path, "done", "--", "-x") == 1
    assert capsys.readouterr().err.startswith("error: invalid id '-x'")


def test_cli_done_with_dash_id_without_double_dash_exits_2(path: Path) -> None:
    with pytest.raises(SystemExit) as info:
        run(path, "done", "-x")
    assert info.value.code == 2


def test_cli_negative_number_id_is_reported_as_invalid_id(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(path, "done", "-3") == 1
    assert capsys.readouterr().err.startswith("error: invalid id '-3'")


# Task 14: end to end --------------------------------------------------------------------------


def test_cli_missing_file_lists_empty_and_creates_nothing(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(path, "list") == 0
    assert capsys.readouterr().out == "no tasks yet\n"
    assert not path.exists()


@pytest.mark.parametrize("content", [b"not json", b"{}", b"\xff\xfe"])
def test_cli_corrupt_file_exit_1_and_file_unchanged(path: Path, capsys: pytest.CaptureFixture[str], content: bytes) -> None:
    path.write_bytes(content)
    assert run(path, "list") == 1
    assert capsys.readouterr().err.startswith("error: cannot read")
    assert run(path, "add", "a") == 1
    assert path.read_bytes() == content


def test_cli_zero_byte_file_exit_1(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path.write_bytes(b"")
    assert run(path, "list") == 1
    assert "error: cannot read" in capsys.readouterr().err


def test_cli_unwritable_storage_exit_1_with_clear_message(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    assert run(blocker / "todo.json", "add", "a") == 1
    err = capsys.readouterr().err
    assert err.startswith("error: cannot write") and "Traceback" not in err


def test_cli_full_round_trip(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(path, "add", "one") == 0
    assert run(path, "add", "two") == 0
    assert run(path, "done", "2") == 0
    assert run(path, "reopen", "2") == 0
    assert run(path, "delete", "2") == 0
    assert run(path, "add", "three") == 0
    capsys.readouterr()
    assert run(path, "list") == 0
    assert capsys.readouterr().out.splitlines() == ["1  open  one", "3  open  three"]


# Task 8, 10, 12, 13, 15: gaps found when checking the plan --------------------------------------


def test_cli_invalid_id_message_is_exact(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(path, "done", "abc") == 1
    assert capsys.readouterr().err == "error: invalid id 'abc': an id is a whole number such as 1\n"


def test_cli_title_with_control_character_is_stored_raw_and_printed_escaped(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    title = "a\x1b[31mb"
    assert run(path, "add", title) == 0
    assert capsys.readouterr().out == "added task 1: open - a\\x1b[31mb\n"
    assert TodoList(path).list()[0].title == title
    assert json.loads(path.read_text(encoding="utf-8"))["items"][0]["title"] == title


def test_ids_stay_unique_across_sequential_instances(path: Path) -> None:
    seen: list[int] = []
    for round_number in range(3):
        todos = TodoList(path)
        seen.append(todos.add(f"task {round_number}").id)
        if round_number == 1:
            TodoList(path).delete(seen[-1])
    assert len(set(seen)) == len(seen)


def test_app_uses_postponed_annotations() -> None:
    tree = ast.parse((ROOT / "todo" / "app.py").read_text(encoding="utf-8"))
    future = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "__future__"]
    assert any(alias.name == "annotations" for node in future for alias in node.names)


def test_module_runs_as_python_m_todo_cli(tmp_path: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    base = [sys.executable, "-m", "todo.cli"]
    added = subprocess.run([*base, "add", "Buy", "milk"], cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
    assert added.returncode == 0 and added.stdout == "added task 1: open - Buy milk\n"
    listed = subprocess.run([*base, "list"], cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
    assert listed.returncode == 0 and listed.stdout == "1  open  Buy milk\n"
    assert (tmp_path / "todo.json").exists()
    failed = subprocess.run([*base, "done", "abc"], cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
    assert failed.returncode == 1 and failed.stderr.startswith("error: invalid id")
