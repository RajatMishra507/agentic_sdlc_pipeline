# Implementation Report

Implements `artifacts/plan.md` (tasks 1 to 15) for `artifacts/requirements.md` and `artifacts/architecture.md`, honouring the conditions in `artifacts/design-review.md`. The implementation phase was already in progress when this work began, so no second `start` was run.

## Summary of Changes

- `todo/app.py` was rewritten.
  - `Item` now holds `id`, `title` and a string `status` of `open` or `done`.
  - The storage file uses the documented format with `version`, `next_id` and `items`. The loader rejects invalid JSON, invalid UTF-8, wrong types, booleans used as integers, duplicate ids, ids below 1, a `next_id` that is not above every id, a bad status, an unknown or missing version, a directory used as the file, and the old sample format (with advice to move or delete it). A corrupt file is never overwritten.
  - Saving writes a temporary file in the same directory, syncs it and replaces the target with `os.replace`. It creates a missing directory and removes the temporary file on failure. In-memory state is only updated after a successful save.
  - `escape_text` is the one shared helper that shows non-printable characters as visible escapes and leaves printable text, including non-ASCII, unchanged.
  - `parse_id` uses a full ASCII match on `[0-9]+`, a cap of 18 digits and a minimum of 1. It never lets `ValueError` escape, and its message echoes a shortened, escaped copy of the input.
  - `TodoList` has `add`, `list`, `complete`, `reopen` and `delete`. Ids come from a persisted `next_id` and are never reused. Titles are stored exactly as given. Empty or whitespace-only titles are rejected. `list` returns copies. `complete` and `reopen` return `(item, changed)` and do not write on a no-op. `delete` leaves `next_id` unchanged. `format_item` produces the display line.
- `todo/cli.py` was updated.
  - Commands are `add`, `list`, `done`, `reopen` and `delete`, plus `--file`. The sample's `remove` command and `--pending` option are gone.
  - Ids are read as text and validated by `parse_id`.
  - Messages follow the architecture table. Success and no-op messages go to standard output, errors go to standard error as `error: <message>`, and `TodoError` exits with code 1. Usage errors exit with code 2 through `argparse`.
  - Every title or user text in any message passes through `escape_text`.
  - The help text names the default file and states the rule for words that start with a dash. Option abbreviations are switched off.
- `tests/test_todo.py` was replaced with 144 tests that cover plan tasks 1 to 14 and every acceptance criterion AC-1 to AC-13.
- `requirements.txt` is unchanged. No runtime dependency was added.

## Changed Files

- `todo/app.py`
- `todo/cli.py`
- `tests/test_todo.py`
- `artifacts/implementation.md`

## Tests Added or Updated

All sample tests were removed because they check behaviour the approved design changes (whitespace normalisation, the 200-character limit, `--pending`, the `remove` command, boolean `done` and reuse of the highest id). No test was weakened to make code pass. Each removed behaviour is now covered by a test of the new behaviour.

Results: `python3 -m pytest tests/test_todo.py -q` runs 144 tests and all pass. The full suite (`.venv/bin/python -m pytest -q`) passes, including the orchestrator and guard tests that were not touched. The official evidence comes from `run-checks` in the verify phase.

| Area | Tests |
| --- | --- |
| Data model, standard library only (plan 1, 15) | `test_item_status_values`, `test_module_uses_only_standard_library` |
| Loading and validation (plan 2) | missing file, zero-byte file, 20 parametrised corrupt-file cases that check the file is byte-for-byte unchanged, old sample format, directory as path, valid file |
| Atomic save (plan 3) | no temporary files left, missing directory created, documented format, forced `os.replace` failure keeps the old file and memory state |
| Escaping (plan 4) | printable text unchanged, seven control and format character cases |
| Id parsing (plan 5) | valid ids, 13 invalid forms, a 5000-digit id, escaping and shortening of the echoed text |
| Add (plan 6, AC-1, AC-2, AC-13) | unique open task, persistence, no id reuse, six exact-title cases including 10000 characters, five empty-title cases |
| List (plan 7, AC-3, AC-4) | creation order, empty list, copies, no write |
| Complete and reopen (plan 8, AC-5 to AC-8, AC-10) | changes, no-ops that do not write, unknown id for all three change commands |
| Delete (plan 9, AC-9) | removal and `next_id` kept |
| Display line (plan 10) | id, status and title, non-ASCII, escaping |
| Parser (plan 11, AC-12) | all commands, help text, removed commands exit 2 |
| Handlers (plan 12, AC-1 to AC-13) | exact messages, streams and exit codes, unknown and invalid ids (including a 5000-digit id and an escape character) for each command with no change to the file, exact titles, empty titles, escaped output |
| Dash-leading input (plan 13) | see Deviations from Plan for the exact behaviour pinned |
| End to end (plan 14, AC-12) | missing file, corrupt and zero-byte files, unwritable storage, full round trip, and a real `python3 -m todo.cli` process |

Design review conditions: finding 1 (long ids) is covered by the 5000-digit tests in `parse_id` and through the command line, finding 2 (escaping in every message) by the escape-character tests for ids and titles, and finding 3 (dash-leading words) by the dash tests.

## Deviations from Plan

- **Dash-leading words.** Plan task 13 expected that an id such as `-3` without `--` exits with code 2. `argparse` treats a token like `-3` as a negative number, not an option, because the parser defines no option that looks like a number. The result is that `done -3` and `add -5 degrees` work without `--`, with `-3` reported as an invalid id (exit code 1) and `-5 degrees` stored as a title. Words that look like options (`-x`, `-urgent`) still need `--` and exit with code 2 without it. Both behaviours are pinned by tests, and the help text states the rule. The condition in design review finding 3 (documented and tested, exit code stated) is met, but the exit code for a dash-leading id depends on whether it looks like a number.
- **Usage errors raise `SystemExit`.** The plan says `main` returns the exit code. For exit code 2, `argparse` raises `SystemExit(2)` and the tests use `pytest.raises(SystemExit)`. This matches the architecture's exit-code table, which assigns code 2 to `argparse`.
- **Plan task 1 and the test file.** The old test file was removed from the terminal and recreated with the file tool, not edited in place, because every test in it was being replaced.
- **Process note.** `todo/app.py` was first written through a terminal heredoc, not the file edit tool. The file is in an allowed path and its content was checked afterwards, but the edit tool should have been used.
- **Not done, as planned.** `.gitignore` was not changed (outside the writable paths), and concurrent runs against one file are still not coordinated.
