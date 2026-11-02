# Implementation Plan

This plan turns the approved architecture (`artifacts/architecture.md`) into ordered, testable tasks. It honors the design review verdict `APPROVED_WITH_CONDITIONS` (`artifacts/design-review.md`); each condition and finding is mapped to a task below.

Starting point: `todo/app.py`, `todo/cli.py` and `tests/test_todo.py` already exist in the workspace from an earlier cycle and closely match the architecture. The plan therefore treats them as a draft to verify, not as finished work. Each task first checks that the existing behavior matches the requirement and the test proves it, and changes code only where a gap is found. The implementation report must state, per task, whether the code was changed or confirmed as is.

Files the implementation phase may change: `todo/**`, `tests/test_todo.py`, `requirements.txt`. Nothing else is touched.

## Work Breakdown

1. **Baseline and environment check.**
   - Files: none changed. Run the existing suite through `python3 orchestrator.py run-checks` and record the result. The `python3` on this machine lacked `pytest` when checked during planning, so confirm the check runs in an environment that has it; if `requirements.txt` needs a dependency entry, that is the only change to it.
   - Requirements: NFR-1.
   - Test: `tests/test_todo.py::test_module_uses_only_standard_library` and the whole suite passing under `run-checks`.

2. **Id parsing and display escaping.** File: `todo/app.py`. Verify `parse_id` accepts whole numbers of at least 1 up to 18 digits and rejects everything else (text, `0`, `-1`, `1.5`, empty, Unicode digits, 5000-digit text) with `invalid id '<id>': an id is a whole number such as 1`, echoing the id escaped and shortened to 40 characters. Verify `escape_text` leaves printable text, including non-ASCII, unchanged and shows control characters as `\xNN`, `\uNNNN` or `\UNNNNNNNN`.
   - Requirements: FR-11, NFR-3, AC-11.
   - Tests: `test_parse_id_accepts_whole_numbers`, `test_parse_id_rejects_invalid_text`, `test_parse_id_rejects_5000_digit_text_without_value_error`, `test_parse_id_message_escapes_control_characters`, `test_parse_id_message_is_shortened_for_long_text`, `test_escape_keeps_printable_text`, `test_escape_makes_controls_visible`.

3. **Task model and add.** File: `todo/app.py`. Verify `Item`, and `TodoList.add` that gives each new task the next id from the persisted `next_id`, status `open`, the title stored exactly as entered, and rejects empty or whitespace-only titles without writing (D-3, provisional until the human confirms it at approval).
   - Requirements: FR-1, FR-2, NFR-2, NFR-4, AC-1, AC-2, AC-13.
   - Tests: `test_item_status_values`, `test_add_creates_open_task_with_unique_id`, `test_add_persists_across_reload`, `test_id_is_not_reused_after_deleting_newest_task`, `test_title_is_stored_exactly`, `test_empty_and_whitespace_titles_are_rejected_without_writing`.

4. **List and format.** File: `todo/app.py`. Verify `list` returns copies in creation order without writing, and `format_item` returns `<id>  <status>  <title>` with the title escaped.
   - Requirements: FR-4, AC-3.
   - Tests: `test_list_is_in_creation_order`, `test_list_of_empty_list_is_empty`, `test_list_returns_copies`, `test_list_does_not_write`, `test_format_item_shows_id_status_title`, `test_format_item_keeps_non_ascii_title`, `test_format_item_escapes_control_characters`.

5. **Complete and reopen.** File: `todo/app.py`. Verify `complete` and `reopen` change the status and save, return `changed=False` without saving for a no-op, and raise `no task with id <n>` for an unknown id without changing anything.
   - Requirements: FR-6, FR-7, FR-8, FR-9, FR-11, AC-5, AC-6, AC-7, AC-8, AC-10.
   - Tests: `test_complete_open_task`, `test_complete_done_task_is_noop_and_does_not_write`, `test_reopen_done_task`, `test_reopen_open_task_is_noop`, `test_unknown_id_raises_and_changes_nothing`.

6. **Delete.** File: `todo/app.py`. Verify `delete` removes the task, saves, keeps `next_id` unchanged, and raises for an unknown id.
   - Requirements: FR-10, FR-11, NFR-4, AC-9, AC-10.
   - Tests: `test_delete_removes_task`, `test_delete_keeps_next_id`, `test_unknown_id_raises_and_changes_nothing`.

7. **Storage load, validation and atomic save.** File: `todo/app.py`. Verify that a missing file is an empty list and creates nothing; that zero-byte, corrupt, wrong-version, duplicate-id, bad-`next_id`, bad-status, old-format and directory-as-file inputs give a `cannot read` error and leave the file untouched; and that a save is atomic, leaves no temporary file, and keeps the old file when the replace fails. Confirm parent directories are created on save (design review finding 4) and add a short comment in the code stating that parent directories are created and an existing file's permissions are replaced by the owner-only mode of the new file.
   - Requirements: NFR-4, FR-11 (no change on error), AC-2.
   - Tests: `test_missing_file_gives_empty_list_and_creates_nothing`, `test_empty_zero_byte_file_is_reported`, `test_corrupt_file_is_reported_not_overwritten`, `test_old_sample_format_is_rejected_with_advice`, `test_path_that_is_a_directory_is_reported`, `test_valid_file_loads`, `test_save_leaves_no_temp_files`, `test_save_creates_missing_directory`, `test_saved_file_uses_documented_format`, `test_failed_replace_keeps_old_file_and_removes_temp`.

8. **Command line wiring and exact messages.** File: `todo/cli.py`. Verify the parser defines `add`, `list`, `done`, `reopen`, `delete` and `--file`; and that output matches the architecture table exactly: `added task <id>: open - <title>`, `no tasks yet`, `task <id> is now done|open: <title>`, `task <id> is already done|open: <title>`, `deleted task <id>: <title>`, errors as `error: <message>` on stderr with exit 1. Tests compare these as exact strings, not substrings (design review finding 8).
   - Requirements: FR-1, FR-3, FR-4, FR-5, FR-6, FR-7, FR-8, FR-9, FR-10, FR-11, NFR-3, AC-1, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8, AC-9, AC-10, AC-11.
   - Tests: `test_parser_defines_all_commands`, `test_cli_add_prints_id_title_and_status`, `test_cli_add_joins_words_with_single_spaces`, `test_cli_list_order_and_columns`, `test_cli_empty_list_message`, `test_cli_done_and_noop_messages`, `test_cli_reopen_and_noop_messages`, `test_cli_delete_then_list`, `test_cli_unknown_id_exit_1_and_no_change`, `test_cli_invalid_id_exit_1_and_no_change`, `test_cli_errors_go_to_stderr_and_success_to_stdout`, `test_removed_or_missing_commands_exit_2`.

9. **Dash-leading ids and titles (design review condition a, finding 1).** File: `todo/cli.py`, and `tests/test_todo.py` if a test needs sharpening. The accepted behavior is: an id or title that starts with a dash must follow `--`. Without `--`, a word such as `-x` is read as an option and the command exits 2 with an argparse message; `-1` and `-5 degrees` are numbers and are accepted. The help text and epilog must state the `--` rule. This is an explicit, documented exception to AC-11, and the tests pin it so it cannot change silently.
   - Requirements: FR-11, NFR-3, AC-11.
   - Tests: `test_help_names_default_file_and_dash_rule`, `test_cli_done_with_dash_id_after_double_dash_exits_1_with_invalid_id_message`, `test_cli_done_with_dash_id_without_double_dash_exits_2`, `test_cli_negative_number_id_is_reported_as_invalid_id`, `test_cli_add_after_double_dash_stores_dash_title`, `test_cli_add_dash_title_without_double_dash_exits_2_and_adds_nothing`, `test_cli_add_negative_number_title_is_accepted`.

10. **Display escaping as a recorded narrowing of AC-13 (condition b, finding 2).** Files: `todo/app.py`, `todo/cli.py`. Stored titles stay exactly as entered; only printing escapes non-printable characters. Tests cover both sides: printable text with spaces, punctuation and non-ASCII is printed unchanged, and a control character is stored raw but printed escaped. Add a comment next to `escape_text` stating that this narrows "displayed exactly as entered" for non-printable characters only. The architecture record of this decision (D-9) is a human-owned document; the implementation report notes the gap for the human.
    - Requirements: NFR-2, AC-13.
    - Tests: `test_cli_title_with_spaces_punctuation_and_non_ascii_is_stored_exactly`, `test_cli_title_with_control_character_is_escaped_on_output`, `test_title_is_stored_exactly`.

11. **Empty-title rule kept reversible (condition c, finding 3).** Files: `todo/app.py`, `todo/cli.py`. D-3 is provisional until the human confirms it. Keep the rule in a single place (`TodoList.add`) with one test per layer, so that reversing it is a one-line code change and a test change.
    - Requirements: NFR-2.
    - Tests: `test_empty_and_whitespace_titles_are_rejected_without_writing`, `test_cli_empty_title_exit_1`.

12. **Uniqueness limit stated and tested for sequential use (finding 5).** File: `todo/app.py` (docstring or comment), `tests/test_todo.py`. State in the `TodoList` docstring that ids stay unique across sequential runs and that concurrent writers are not supported. Add a test that two `TodoList` instances created one after the other on the same file never produce the same id. No locking is added (D-5).
    - Requirements: NFR-4, AC-2.
    - Tests: a new test named `test_ids_stay_unique_across_sequential_instances` (new), plus `test_id_is_not_reused_after_deleting_newest_task`.

13. **Postponed annotations guard (finding 7).** File: `tests/test_todo.py`. Add a test that `todo.app` imports `annotations` from `__future__`, so the method named `list` cannot break the `list[Item]` annotation. No rename is made, because the architecture fixes the method name.
    - Requirements: NFR-1.
    - Tests: a new test named `test_app_uses_postponed_annotations` (new).

14. **End to end and module entry point.** Files: `todo/cli.py`, `todo/__init__.py`. Verify a full add, list, done, reopen, delete round trip, and that `python3 -m todo.cli` runs from the repository root with only the standard library.
    - Requirements: NFR-1, AC-12, and every FR through the round trip.
    - Tests: `test_cli_full_round_trip`, `test_module_runs_as_python_m_todo_cli`, `test_cli_missing_file_lists_empty_and_creates_nothing`.

15. **Requirement coverage check and final run.** Files: `tests/test_todo.py` only if a gap is found. Build a table of FR-1 to FR-11, NFR-1 to NFR-4 and AC-1 to AC-13 against the passing tests, add a test for any requirement with no test, and run the complete suite through `python3 orchestrator.py run-checks`.
    - Requirements: all.
    - Tests: the whole of `tests/test_todo.py`.

Design review findings handled without a code task, with reasons: finding 6 (FR-11 mentions Create, which takes no id) and finding 9 (D-4 wording) concern wording in the architecture, which only a human can change; the implementation report records them. Finding 4 and 5 are partly handled by tasks 7 and 12, and the remaining architecture text change is left to the human.

## Test Strategy

- **Unit tests for `todo/app.py`:** id parsing, escaping, add, list, complete, reopen, delete, ordering, no-op behavior, id uniqueness, and storage save and load. Use `tmp_path` for every file so tests never touch a real list.
- **CLI tests for `todo/cli.py`:** call `main(argv)` and capture stdout, stderr and the return code. Assert exact message strings and exit codes: 0 for success and no-ops, 1 for `TodoError`, 2 for argparse usage errors. One test starts the module in a subprocess to prove `python3 -m todo.cli`.
- **Edge cases:**
  - Empty input: no tasks, empty title, whitespace-only title, empty id.
  - Missing file: list shows the empty message and creates nothing.
  - Corrupt data: zero-byte file, invalid JSON, wrong type at the top level, wrong version, duplicate ids, `next_id` too low, bad status, old file format, path that is a directory. Each gives a `cannot read` error and leaves the file untouched.
  - Invalid and unknown ids: `abc`, `0`, `-1`, `1.5`, 5000 digits, control characters in the id, id 999.
  - Titles: spaces, punctuation, non-ASCII, a leading dash, a control character.
  - Write failure: a failing replace keeps the old file and removes the temporary file; an unwritable location gives `cannot write`.
- **No-change guarantees:** tests that a no-op or an error does not write the file, by checking that the file is unchanged or that save is not called.
- **Traceability:** each task lists its tests, and task 15 confirms that every FR, NFR and AC has at least one passing test.

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Existing code is assumed correct and gaps are missed. | Every task begins with a verification step against the requirement; task 15 builds a coverage table; the report records "confirmed" or "changed" per task. |
| `pytest` is missing in the interpreter that `run-checks` uses. | Task 1 runs `run-checks` first and, if needed, records the dependency in `requirements.txt` (the only writable dependency file) or reports the environment problem to the human. |
| The human changes D-1, D-3, D-4 or D-6 at approval. | Task 11 keeps the empty-title rule in one place; message strings are pinned by tests, so a change is a small, visible edit. |
| Dash-leading ids give a confusing argparse error (finding 1). | Task 9 documents the rule in the help text and pins it with tests; the exception to AC-11 is recorded in the implementation report. |
| Display escaping is read as a violation of AC-13. | Task 10 limits escaping to non-printable characters and tests both sides; the human owns the architecture note (D-9). |
| Overlapping runs could duplicate an id. | Task 12 states the limit in the code and tests sequential uniqueness; locking is out of scope (D-5). |
| Files outside the writable set need a change. | Do not edit them. The implementation report lists the need and the human decides. |
| Tests touch real files or the working directory. | All tests use `tmp_path`; the default `todo.json` is never read or written by a test. |

## Definition of Done

- Every task above is complete, and its tests exist and pass.
- Every FR, NFR and AC in `artifacts/requirements.md` maps to at least one passing test (task 15).
- `python3 orchestrator.py run-checks` reports a passing run for the full suite.
- Only `todo/**`, `tests/test_todo.py` and `requirements.txt` changed; no protected file was edited.
- Every design review condition (a to d) is addressed by a task, and the remaining findings have a task or a recorded reason.
- `artifacts/implementation.md` lists, per task, what changed and any deviation from this plan, and the review phase returns an approved verdict.
