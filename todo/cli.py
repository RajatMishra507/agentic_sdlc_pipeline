"""Command line interface for the todo list."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from todo.app import TodoError, TodoList, escape_text, format_item, parse_id

DEFAULT_FILE = Path("todo.json")

EPILOG = (
    "A title or id that starts with a dash must follow '--', for example: todo add -- -urgent. "
    "Without '--' such a word is read as an option and the command exits with code 2."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="todo", description="Simple todo list", epilog=EPILOG, allow_abbrev=False
    )
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE, help="storage file (default: todo.json in the current directory)")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="add a task", epilog=EPILOG, allow_abbrev=False)
    add.add_argument("title", nargs="+", help="task title; words are joined with single spaces")
    sub.add_parser("list", help="list tasks in creation order", allow_abbrev=False)
    for name, text in (
        ("done", "mark a task as done"),
        ("reopen", "mark a task as open again"),
        ("delete", "delete a task"),
    ):
        cmd = sub.add_parser(name, help=text, epilog=EPILOG, allow_abbrev=False)
        cmd.add_argument("id", help="task id, a whole number such as 1")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        todos = TodoList(args.file)
        if args.command == "add":
            item = todos.add(" ".join(args.title))
            print(f"added task {item.id}: open - {escape_text(item.title)}")
        elif args.command == "list":
            items = todos.list()
            for item in items:
                print(format_item(item))
            if not items:
                print("no tasks yet")
        elif args.command in ("done", "reopen"):
            item_id = parse_id(args.id)
            target = "done" if args.command == "done" else "open"
            action = todos.complete if args.command == "done" else todos.reopen
            item, changed = action(item_id)
            state = f"is now {target}" if changed else f"is already {target}"
            print(f"task {item.id} {state}: {escape_text(item.title)}")
        elif args.command == "delete":
            item = todos.delete(parse_id(args.id))
            print(f"deleted task {item.id}: {escape_text(item.title)}")
    except TodoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
