"""Todo list logic: tasks, validation, escaping and JSON persistence (standard library only)."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

STORAGE_VERSION = 1
MAX_ID_DIGITS = 18
STATUSES = ("open", "done")
_ID_PATTERN = re.compile(r"[0-9]+", re.ASCII)
_ECHO_LIMIT = 40


class TodoError(Exception):
    """Raised for invalid input or unusable storage. The message is written for the end user."""


@dataclass
class Item:
    id: int
    title: str
    status: str = "open"


def escape_text(text: str) -> str:
    """Return text with every non-printable character shown as a visible escape.

    Printable text, including spaces, punctuation and non-ASCII letters, is unchanged.
    Titles are stored exactly as entered; only printing escapes, so "displayed exactly as
    entered" is narrowed for non-printable characters only.
    """
    out: list[str] = []
    for ch in text:
        if ch.isprintable():
            out.append(ch)
            continue
        code = ord(ch)
        if code <= 0xFF:
            out.append(f"\\x{code:02x}")
        elif code <= 0xFFFF:
            out.append(f"\\u{code:04x}")
        else:
            out.append(f"\\U{code:08x}")
    return "".join(out)


def parse_id(text: str) -> int:
    """Convert command-line text into a task id or raise TodoError."""
    if _ID_PATTERN.fullmatch(text) and len(text) <= MAX_ID_DIGITS:
        value = int(text)
        if value >= 1:
            return value
    shown = text if len(text) <= _ECHO_LIMIT else text[:_ECHO_LIMIT] + "..."
    raise TodoError(f"invalid id '{escape_text(shown)}': an id is a whole number such as 1")


def format_item(item: Item) -> str:
    return f"{item.id}  {item.status}  {escape_text(item.title)}"


def _is_int(value: object) -> bool:
    return type(value) is int


class TodoList:
    """An ordered list of tasks stored in a JSON file. Each change is saved atomically.

    Ids stay unique across sequential runs. Concurrent writers are not supported: two
    overlapping runs could lose an update or hand out the same id.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.next_id = 1
        self.items: list[Item] = []
        if self.path.exists():
            self._load()

    def _bad(self, reason: str) -> TodoError:
        return TodoError(f"cannot read {escape_text(str(self.path))}: {reason}")

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise self._bad(f"not readable UTF-8 JSON ({exc})") from exc
        if not isinstance(data, dict):
            raise self._bad("the top level must be a JSON object")
        raw_items = data.get("items")
        if "next_id" not in data and "version" not in data and isinstance(raw_items, list) and any(
            isinstance(r, dict) and "done" in r for r in raw_items
        ):
            raise self._bad("this is the old file format; move or delete the file to start a new list")
        if not _is_int(data.get("version")) or data["version"] != STORAGE_VERSION:
            raise self._bad(f"unsupported or missing version (expected {STORAGE_VERSION})")
        next_id = data.get("next_id")
        if not _is_int(next_id) or next_id < 1:
            raise self._bad("next_id must be a whole number of at least 1")
        if not isinstance(raw_items, list):
            raise self._bad("items must be a list")
        items: list[Item] = []
        seen: set[int] = set()
        for position, raw in enumerate(raw_items, start=1):
            if not isinstance(raw, dict):
                raise self._bad(f"item {position} is not an object")
            item_id, title, status = raw.get("id"), raw.get("title"), raw.get("status")
            if not _is_int(item_id) or item_id < 1:
                raise self._bad(f"item {position} has an invalid id")
            if not isinstance(title, str):
                raise self._bad(f"item {position} has an invalid title")
            if status not in STATUSES:
                raise self._bad(f"item {position} has an invalid status")
            if item_id in seen:
                raise self._bad(f"id {item_id} appears more than once")
            seen.add(item_id)
            items.append(Item(id=item_id, title=title, status=status))
        if seen and next_id <= max(seen):
            raise self._bad("next_id must be greater than every item id")
        self.items = items
        self.next_id = next_id

    def _save(self, items: list[Item], next_id: int) -> None:
        # Missing parent directories are created (all levels). The result is an owner-only regular
        # file (mkstemp). An existing file's permissions are not preserved, and a symbolic link used
        # as the storage path is replaced, not followed.
        payload = json.dumps(
            {
                "version": STORAGE_VERSION,
                "next_id": next_id,
                "items": [{"id": i.id, "title": i.title, "status": i.status} for i in items],
            },
            indent=2,
            ensure_ascii=False,
        )
        target = escape_text(str(self.path))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".todo-", suffix=".tmp")
        except OSError as exc:
            raise TodoError(f"cannot write {target}: {exc}") from exc
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except OSError as exc:
            Path(tmp).unlink(missing_ok=True)
            raise TodoError(f"cannot write {target}: {exc}") from exc

    def _find(self, item_id: int) -> Item:
        for item in self.items:
            if item.id == item_id:
                return item
        raise TodoError(f"no task with id {item_id}")

    def add(self, title: str) -> Item:
        if not title.strip():
            raise TodoError("title must not be empty")
        item = Item(id=self.next_id, title=title, status="open")
        self._save([*self.items, item], self.next_id + 1)
        self.items.append(item)
        self.next_id += 1
        return replace(item)

    def list(self) -> list[Item]:
        return [replace(i) for i in self.items]

    def _set_status(self, item_id: int, status: str) -> tuple[Item, bool]:
        item = self._find(item_id)
        if item.status == status:
            return replace(item), False
        changed = [replace(i, status=status) if i.id == item_id else i for i in self.items]
        self._save(changed, self.next_id)
        item.status = status
        return replace(item), True

    def complete(self, item_id: int) -> tuple[Item, bool]:
        return self._set_status(item_id, "done")

    def reopen(self, item_id: int) -> tuple[Item, bool]:
        return self._set_status(item_id, "open")

    def delete(self, item_id: int) -> Item:
        item = self._find(item_id)
        self._save([i for i in self.items if i.id != item_id], self.next_id)
        self.items.remove(item)
        return item
