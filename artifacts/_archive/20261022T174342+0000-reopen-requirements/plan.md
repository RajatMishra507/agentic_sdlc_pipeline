# Implementation Plan

Plan for `artifacts/requirements.md` (FR-1 to FR-11, NFR-1 to NFR-4, AC-1 to AC-13) using `artifacts/architecture.md` and the conditions in `artifacts/design-review.md` (verdict `APPROVED_WITH_CONDITIONS`, findings 1 to 9). Only `todo/**`, `tests/test_todo.py` and `requirements.txt` may be written in the implementation phase.

Starting point: `todo/app.py` and `todo/cli.py` are a sample that does not meet the requirements (see the gap table in the architecture). The existing tests in `tests/test_todo.py` check sample behaviour that the design deliberately changes: whitespace normalisation, the 200-character limit, `include_done`, the `remove` command and boolean `done`. Task 1 replaces them. Each later task adds its tests to the same file, so the suite stays green at the end of every task.

Names used below: `escape_text` is the one shared helper that makes control characters visible (design review finding 2). `MAX_ID_DIGITS` is 18. `STORAGE_VERSION` is 1.

## Work Breakdown

1. **Reset the test file and define the data model.**
   - File: `todo/app.py`, `tests/test_todo.py`.
   - Change: remove `MAX_TITLE_LENGTH`. `Item` becomes `id: int`, `title: str`, `status: str` with `status` being `open` or `done`. Add `TodoError`, `STORAGE_VERSION` and `MAX_ID_DIGITS`. Delete every test that checks the sample behaviour named above and replace the file with a fixture for a temporary storage path and a small helper that writes a storage file.
   - Requirements: FR-2, FR-3, NFR-1.
   - Test: `test_item_status_values`, which builds an `Item` and checks that the status is the string `open` or `done`, and `test_module_uses_only_standard_library`, which parses `todo/app.py` and `todo/cli.py` with `ast` and checks that every import is from the standard library (`sys.stdlib_module_names`) or from `todo`.

2. **Load and validate the storage file.**
   - File: `todo/app.py`, `tests/test_todo.py`.
   - Change: `TodoList.__init__` loads the file. A missing file gives an empty list with `next_id` 1 and creates nothing. The loader reads UTF-8 JSON and accepts only the format in the architecture: an object with `version` equal to 1, an integer `next_id`, and a list `items` of objects with integer `id`, string `title` and `status` of `open` or `done`. It rejects booleans where an integer is expected (design review finding 5), duplicate ids, ids below 1, a `next_id` that is not greater than every id, an unknown version, a top-level value that is not an object, and files from the old sample (a `done` field and no `next_id`), the last with a message that says to move or delete the file. A path that is a directory is reported as `TodoError`. A corrupt file is never overwritten.
   - Requirements: FR-4, NFR-2, NFR-3, NFR-4, and edge cases for corrupt data and a missing file.
   - Test: `test_missing_file_gives_empty_list_and_creates_nothing`, `test_empty_zero_byte_file_is_reported`, parametrised `test_corrupt_file_is_reported_not_overwritten` (invalid JSON, invalid UTF-8 bytes, top-level list, items not a list, missing field, wrong field type, boolean id, boolean `next_id`, duplicate id, id 0, negative id, bad status, `next_id` not above the highest id, version 2, missing version), `test_old_sample_format_is_rejected_with_advice`, `test_path_that_is_a_directory_is_reported`.

3. **Atomic save.**
   - File: `todo/app.py`, `tests/test_todo.py`.
   - Change: `_save` writes the full format (including `version` and `next_id`) to a temporary file in the same directory, flushes and syncs it, and replaces the target with `os.replace`. It creates a missing parent directory. On failure it removes the temporary file, keeps the previous file and raises `TodoError`. A comment in the function states the chosen behaviour for permissions and for a symbolic link used as the storage path: the result is an owner-only regular file and a link is replaced, not followed (design review finding 6).
   - Requirements: FR-2, NFR-2, NFR-4.
   - Test: `test_save_leaves_no_temp_files`, `test_save_creates_missing_directory`, `test_failed_replace_keeps_old_file_and_removes_temp` (using `monkeypatch` on `os.replace`), `test_saved_file_uses_documented_format`.

4. **Shared text escaping.**
   - File: `todo/app.py`, `tests/test_todo.py`.
   - Change: add `escape_text(text: str) -> str`, which returns ordinary printable text unchanged, including spaces, punctuation and non-ASCII letters, and replaces every other character (control characters, escape, newline, tab, lone surrogates, unassigned or format characters) with a visible `\xNN`, `\uNNNN` or `\UNNNNNNNN` escape. It does not alter the stored title.
   - Requirements: NFR-2, NFR-3, AC-13, design review findings 2 and 4.
   - Test: `test_escape_keeps_printable_text` (spaces, punctuation, accents, CJK, emoji), parametrised `test_escape_makes_controls_visible` (escape character, newline, tab, carriage return, NUL, a right-to-left override character).

5. **Id parsing.**
   - File: `todo/app.py`, `tests/test_todo.py`.
   - Change: add `parse_id(text: str) -> int`. It uses `re.fullmatch(r"[0-9]+", text)` with `re.ASCII`, requires 1 to `MAX_ID_DIGITS` digits and a value of at least 1, and never lets `ValueError` escape. Anything else raises `TodoError` with a message of the form `invalid id <escaped text>: an id is a whole number such as 1`, where the echoed text passes through `escape_text` and is shortened to a fixed length with a marker when long (design review findings 1 and 2).
   - Requirements: FR-11, AC-10, AC-11, NFR-3.
   - Test: parametrised `test_parse_id_accepts_whole_numbers` (`1`, `007`, `999999999999999999`), parametrised `test_parse_id_rejects_invalid_text` (`abc`, `1.5`, `-3`, `0`, empty string, a space, `1 `, `1\n`, Arabic-Indic digit text, `+1`, `1e3`), `test_parse_id_rejects_5000_digit_text_without_value_error`, `test_parse_id_message_escapes_control_characters`, `test_parse_id_message_is_shortened_for_long_text`.

6. **Add a task.**
   - File: `todo/app.py`, `tests/test_todo.py`.
   - Change: `TodoList.add(title)` rejects an empty or whitespace-only title (decision D-2), otherwise stores the title exactly as given with no trimming, normalising or length limit. The new item gets `next_id`, status `open`, is appended, `next_id` increases by one, and the list is saved. Validation happens before any change.
   - Requirements: FR-1, FR-2, FR-3, NFR-2, NFR-4, AC-1, AC-2, AC-13.
   - Test: `test_add_creates_open_task_with_unique_id` (AC-1), `test_add_persists_across_reload`, `test_id_is_not_reused_after_deleting_newest_task` (AC-2), `test_title_is_stored_exactly` (spaces, punctuation, leading and trailing spaces, non-ASCII, a 10000-character title, AC-13), parametrised `test_empty_and_whitespace_titles_are_rejected_without_writing` (empty string, spaces, tab, newline).

7. **List tasks.**
   - File: `todo/app.py`, `tests/test_todo.py`.
   - Change: `TodoList.list()` takes no arguments and returns a new list of new `Item` objects in creation order, so a caller cannot change stored state through it (design review finding 8). It never writes. Keep `from __future__ import annotations` at the top of the module because the method name `list` shadows the built-in inside the class body.
   - Requirements: FR-4, FR-5, AC-3, AC-4.
   - Test: `test_list_is_in_creation_order` (A, B, C, AC-3), `test_list_of_empty_list_is_empty`, `test_list_returns_copies` (changing a returned item does not change a later `list()` or the file), `test_list_does_not_write`.

8. **Complete and reopen.**
   - File: `todo/app.py`, `tests/test_todo.py`.
   - Change: `complete(item_id)` and `reopen(item_id)` each return `(item, changed)`. A task in the other status is changed, saved and returned with `True`. A task already in the target status is left alone, not written, and returned with `False`. An id that matches no task raises `TodoError` with the text `no task with id N` and changes nothing.
   - Requirements: FR-6, FR-7, FR-8, FR-9, FR-11, AC-5, AC-6, AC-7, AC-8, AC-10.
   - Test: `test_complete_open_task` (AC-5), `test_complete_done_task_is_noop_and_does_not_write` (AC-6, checks the file modification is not triggered by comparing contents and by a `monkeypatch` on `_save`), `test_reopen_done_task` (AC-7), `test_reopen_open_task_is_noop` (AC-8), `test_complete_and_reopen_unknown_id_raise_and_change_nothing` (AC-10).

9. **Delete.**
   - File: `todo/app.py`, `tests/test_todo.py`.
   - Change: `TodoList.delete(item_id)` removes the task, saves and returns it. It leaves `next_id` unchanged. Replace the sample's `remove` method. An unknown id raises `TodoError` with `no task with id N` and changes nothing.
   - Requirements: FR-10, FR-11, NFR-4, AC-9, AC-10.
   - Test: `test_delete_removes_task` (AC-9), `test_delete_unknown_id_raises_and_changes_nothing` (AC-10), `test_delete_keeps_next_id`.

10. **Display line for a task.**
    - File: `todo/app.py`, `tests/test_todo.py`.
    - Change: add `format_item(item: Item) -> str`, producing `{id}  {status}  {escaped title}`.
    - Requirements: FR-3, FR-4, NFR-2, NFR-3, AC-13.
    - Test: `test_format_item_shows_id_status_title`, `test_format_item_keeps_non_ascii_title`, `test_format_item_escapes_control_characters`.

11. **Command line parser.**
    - File: `todo/cli.py`, `tests/test_todo.py`.
    - Change: `build_parser()` defines `--file` (default `todo.json`, with the default named in the help text, design review finding 7) and the commands `add` (one or more words), `list` (no arguments), `done ID`, `reopen ID` and `delete ID`, where `ID` is declared as text so `parse_id` owns the validation. Remove the `remove` command and the `--pending` option. Add an epilog to the help text that states that a title or id that starts with a dash must follow `--`, for example `todo add -- -5 degrees`.
    - Requirements: FR-1, FR-8, FR-10, FR-11, NFR-1, AC-12.
    - Test: `test_parser_defines_all_commands`, `test_help_names_default_file_and_dash_rule`, `test_old_remove_command_is_gone` (exit code 2).

12. **Command handlers, messages and exit codes.**
    - File: `todo/cli.py`, `tests/test_todo.py`.
    - Change: `main(argv)` runs one command and returns 0 on success, including a no-op, 1 on `TodoError` and lets `argparse` return 2 for usage errors. Success and no-op messages go to standard output, errors go to standard error as `error: <message>`. The messages follow the architecture table: `added task N: open - TITLE`, one `format_item` line per task or `no tasks yet`, `task N is now done: TITLE`, `task N is already done: TITLE`, `task N is now open: TITLE`, `task N is already open: TITLE`, `deleted task N: TITLE`. Every title or user text in any message goes through `escape_text`. `add` joins its words with one space, so a single quoted argument is stored unchanged. `TodoError` produces no stack trace and other exceptions are not caught.
    - Requirements: FR-1 to FR-11, NFR-3, AC-1 to AC-13.
    - Test: `test_cli_add_prints_id_title_and_status` (AC-1), `test_cli_list_order_and_columns` (AC-3), `test_cli_empty_list_message` (AC-4), `test_cli_done_and_noop_messages` (AC-5, AC-6), `test_cli_reopen_and_noop_messages` (AC-7, AC-8), `test_cli_delete_then_list` (AC-9), parametrised `test_cli_unknown_id_exit_1_and_no_change` for `done`, `reopen` and `delete` with id 999 (AC-10), parametrised `test_cli_invalid_id_exit_1_and_no_change` with `abc`, `1.5`, `0`, a 5000-digit id and an id with an escape character, which also checks that standard error contains no raw escape character (AC-11, design review findings 1 and 2), `test_cli_title_with_spaces_punctuation_and_non_ascii_is_stored_exactly` (AC-13), `test_cli_empty_title_exit_1`, `test_cli_errors_go_to_stderr_and_success_to_stdout`, `test_cli_title_with_control_character_is_escaped_on_output`.

13. **Dash-leading input.**
    - File: `todo/cli.py`, `tests/test_todo.py`.
    - Change: make the behaviour of titles and ids that begin with `-` deliberate and visible (design review finding 3). After `--` they are accepted as text. Without `--` the standard `argparse` usage error with exit code 2 is the documented result. Where a small parser setting makes this clearer, the implementer may use it, provided the tests below still pass.
    - Requirements: FR-1, FR-11, NFR-2, AC-11, AC-13.
    - Test: `test_cli_add_after_double_dash_stores_dash_title`, `test_cli_add_dash_title_without_double_dash_exits_2_and_adds_nothing`, `test_cli_done_with_dash_id_after_double_dash_exits_1_with_invalid_id_message`, `test_cli_done_with_dash_id_without_double_dash_exits_2`.

14. **Persistence and error edge cases through the command line.**
    - File: `todo/cli.py`, `tests/test_todo.py`.
    - Change: no new behaviour. This task adds the end-to-end checks that prove the pieces work together through `main(argv)` with a temporary file.
    - Requirements: FR-4, FR-5, NFR-3, NFR-4, AC-2, AC-12.
    - Test: `test_cli_missing_file_lists_empty_and_creates_nothing`, `test_cli_corrupt_file_exit_1_and_file_unchanged`, `test_cli_zero_byte_file_exit_1`, `test_cli_unwritable_storage_exit_1_with_clear_message` (a path inside a regular file), `test_cli_full_round_trip` (add, list, done, reopen, delete, add again and check the new id was never used), `test_module_runs_as_python_m_todo_cli` (starts `python3 -m todo.cli` with `subprocess` in a temporary working directory and checks the output and exit code, AC-12).

15. **Dependencies and cleanup.**
    - File: `requirements.txt`, `todo/__init__.py`.
    - Change: confirm that no runtime dependency is added. `requirements.txt` keeps only test tooling that already exists (`pytest`), and no third-party import appears under `todo/`. Remove unused imports and the unused `dataclasses.asdict` import if it is no longer needed.
    - Requirements: NFR-1.
    - Test: `test_module_uses_only_standard_library` from task 1, plus the full run in the Definition of Done.

Order notes: tasks 1 to 3 give a safe storage layer, 4 and 5 give the shared helpers that later tasks depend on, 6 to 10 finish `todo/app.py`, and 11 to 15 build `todo/cli.py` on top of it.

## Test Strategy

All tests live in `tests/test_todo.py` and use `pytest` with a temporary directory per test, so no test touches a real `todo.json`. Run with `python3 -m pytest -q`, and for the evidence required by the pipeline, `python3 orchestrator.py run-checks`.

- **Unit tests for `todo/app.py`.** One group per public function: `parse_id`, `escape_text`, `format_item`, and each `TodoList` method (`add`, `list`, `complete`, `reopen`, `delete`). Each group covers the success case, the no-op case where one exists, the unknown-id case, and the check that a failed call changes neither memory nor the file.
- **CLI tests for `todo/cli.py`.** Call `main(argv)` with `--file` pointing at the temporary path and read output with `capsys`. Assert exact exit codes (0, 1, 2), the stream each message goes to, and the message text from the architecture table. One test starts the real `python3 -m todo.cli` process to prove the command-line entry point (AC-12).
- **Edge cases.**
  - Empty input: empty and whitespace-only titles, an empty id, a zero-byte storage file, an empty list.
  - Missing file: listing creates nothing, the first add creates the file and any missing directory.
  - Corrupt data: invalid JSON, invalid UTF-8, wrong types, booleans as integers, duplicate ids, `next_id` too low, bad status, bad version, the old sample format, and a directory used as the file. In every case the file is left byte-for-byte unchanged.
  - Hostile input: a 5000-digit id, an id or title with an escape character or newline, a very long title, dash-leading words.
  - Failed write: `os.replace` forced to fail with `monkeypatch`, which must keep the old file and remove the temporary file.
- **Traceability checks.** Every acceptance criterion AC-1 to AC-13 has at least one test named in this plan. The table below maps them.
- **Not tested.** Two simultaneous runs against the same file, accepted as a limitation in the architecture and in the design review risks.

| Acceptance criterion | Tests (task) |
| --- | --- |
| AC-1 | `test_add_creates_open_task_with_unique_id` (6), `test_cli_add_prints_id_title_and_status` (12) |
| AC-2 | `test_id_is_not_reused_after_deleting_newest_task` (6), `test_cli_full_round_trip` (14) |
| AC-3 | `test_list_is_in_creation_order` (7), `test_cli_list_order_and_columns` (12) |
| AC-4 | `test_list_of_empty_list_is_empty` (7), `test_cli_empty_list_message` (12) |
| AC-5 | `test_complete_open_task` (8), `test_cli_done_and_noop_messages` (12) |
| AC-6 | `test_complete_done_task_is_noop_and_does_not_write` (8), `test_cli_done_and_noop_messages` (12) |
| AC-7 | `test_reopen_done_task` (8), `test_cli_reopen_and_noop_messages` (12) |
| AC-8 | `test_reopen_open_task_is_noop` (8), `test_cli_reopen_and_noop_messages` (12) |
| AC-9 | `test_delete_removes_task` (9), `test_cli_delete_then_list` (12) |
| AC-10 | tasks 8 and 9 unknown-id tests, `test_cli_unknown_id_exit_1_and_no_change` (12) |
| AC-11 | parse_id tests (5), `test_cli_invalid_id_exit_1_and_no_change` (12), dash tests (13) |
| AC-12 | `test_parser_defines_all_commands` (11), `test_module_runs_as_python_m_todo_cli` (14) |
| AC-13 | `test_title_is_stored_exactly` (6), `test_format_item_keeps_non_ascii_title` (10), `test_cli_title_with_spaces_punctuation_and_non_ascii_is_stored_exactly` (12) |

## Design Review Conditions and Findings

Every finding in `artifacts/design-review.md` is handled by a task or has a stated reason.

| Finding | Handling |
| --- | --- |
| 1 Very long ids raise `ValueError` (mandatory condition) | Task 5 full match on ASCII digits with a length cap, tests in tasks 5 and 12 |
| 2 Raw user text in error messages (mandatory condition) | Tasks 4, 5 and 12 use one `escape_text` helper for every user-supplied string in any output |
| 3 Titles and ids that start with a dash (mandatory condition) | Task 13 documents the `--` rule and tests both exit codes, task 11 puts it in the help text |
| 4 Escaping versus "exactly as entered" | Tasks 4, 10 and 12 test that ordinary and non-ASCII text is unchanged and a control character is escaped. The exception to AC-13 is recorded in the Definition of Done |
| 5 Version and boolean checks in the loader | Task 2 tests the version, booleans for `id` and `next_id`, and the other load checks |
| 6 Permissions and symbolic link behaviour of the atomic write | Task 3 states the behaviour in a code comment and does not promise preservation. No test pins the permissions, because the behaviour is platform-dependent |
| 7 Default `todo.json` in the working directory | Task 11 names the default file in `--help`. Adding `todo.json` to the repository ignore file is not planned because `.gitignore` is outside the writable paths for the implementation phase. The human may add it, and every test uses a temporary file, so tests never create a `todo.json` in the repository |
| 8 `list` returns shared mutable items | Task 7 returns new `Item` objects and tests it |
| 9 Testing messages, streams and exit codes | Task 12 asserts exact messages, streams and exit codes through `main(argv)` |
| Condition 4: human confirms D-1 to D-4 | Not a code task. It is a human decision recorded at approval. The plan follows D-1 to D-4 as written, and if a decision changes, tasks 6, 11 and 12 are the ones to revisit |

## Risks and Mitigations

- **The sample tests conflict with the new design.** Tests for normalisation, the length limit, `--pending` and `remove` would fail against the new behaviour. Mitigation: task 1 removes them first and replaces the file, so the suite is not left half red.
- **Leftover sample behaviour.** The sample's `max(id) + 1` rule, whitespace normalisation, boolean `done` and `remove` command are easy to leave behind. Mitigation: dedicated tests (tasks 6, 8, 9, 11) fail if any of them is still present.
- **`argparse` surprises.** Leading dashes, abbreviations of long options and the exit code 2 behaviour are easy to get wrong. Mitigation: task 13 pins the behaviour with tests, and ids are plain text so `parse_id` owns all id validation.
- **Escaping applied inconsistently.** One missed message would reintroduce the terminal-injection risk. Mitigation: a single helper, and tests in task 12 that put an escape character in an id, a title and a unique error path, then check standard output and standard error for raw escape characters.
- **Platform-dependent checks.** File permission and symbolic link behaviour differ between systems. Mitigation: the tests use `monkeypatch` to force failures and do not depend on read-only directories, which behave differently when run as an administrator.
- **Open questions answered by the design (D-1 to D-4).** If the human changes one, tests and messages change. Mitigation: the decisions are listed with the tasks that depend on them, and the human confirms them at approval.
- **Scope creep.** Escaping and strict validation go beyond the requirements. Mitigation: no extra commands, options or dependencies are planned beyond the five commands and `--file`.
- **Concurrent runs.** Not coordinated. Accepted in the architecture, not tested.

## Definition of Done

- All tasks 1 to 15 are complete and every acceptance criterion AC-1 to AC-13 maps to at least one passing test.
- `python3 orchestrator.py run-checks` records a passing result for the whole suite, and the verify phase cites that audit evidence.
- The review phase returns an approved verdict.
- The three mandatory design review conditions (findings 1, 2 and 3) are met and each has a named test.
- Only `todo/**`, `tests/test_todo.py` and `requirements.txt` changed in the implementation phase, and no runtime dependency outside the standard library was added.
- The documented exception to AC-13 holds: ordinary, punctuation and non-ASCII text is stored and displayed exactly, while control characters are stored exactly but shown as visible escapes in output.
- No placeholder markers, secrets or `.env` reads appear in any artifact or source file.
