# Verification Report

Verification of the implementation against `artifacts/requirements.md`, after the approved review in `artifacts/review.md`. The evidence below comes from `run-checks`, not from memory or from earlier test runs.

## Commands Executed

1. `.venv/bin/python orchestrator.py run-checks`, which recorded audit entry 50. The project virtual environment was used because the system `python3` has no `pytest`.
2. `python3 orchestrator.py --json audit --event checks.run --tail 1`, to read the audit sequence number and the recorded counts.

No source file was changed after the run.

## Results

Audit entry 50 records the command `python -m pytest -q tests` with exit code 0, 336 passed, 0 failed and 0 errors, in about 2 seconds. The pytest output ended with `336 passed in 1.87s`.

Earlier attempts in this phase did not produce usable evidence, and they are listed so the history is complete:

- Entry 42 failed with exit code 1 because the system `python3` has no `pytest`, so no test ran.
- Entry 44 ran in the virtual environment and exited 0, but recorded `passed: 0`. The `addopts = "-q"` setting in `pyproject.toml` combined with the `-q` that `run-checks` adds, which hides the summary line that carries the count. A human removed that setting before entry 50.

Entries 42 and 44 are not cited as evidence. Entry 50 postdates the start of this phase and the source tree was unchanged while it ran.

## Requirement Coverage

Each requirement is mapped to tests in `tests/test_todo.py`. All 144 tests in that file ran inside the 336 passed in entry 50, together with the orchestrator and guard tests. The mapping comes from the plan and the test names, and it was not re-derived from the run output, which shows only dots.

| Requirement | Tests that cover it in `tests/test_todo.py` | Status |
| --- | --- | --- |
| FR-1 | `test_add_creates_open_task_with_unique_id`, `test_cli_add_prints_id_title_and_status` | covered |
| FR-2 | `test_add_creates_open_task_with_unique_id`, `test_id_is_not_reused_after_deleting_newest_task` | covered |
| FR-3 | `test_cli_add_prints_id_title_and_status`, `test_format_item_shows_id_status_title` | covered |
| FR-4 | `test_list_is_in_creation_order`, `test_cli_list_order_and_columns` | covered |
| FR-5 | `test_list_of_empty_list_is_empty`, `test_cli_empty_list_message` | covered |
| FR-6 | `test_complete_open_task`, `test_cli_done_and_noop_messages` | covered |
| FR-7 | `test_complete_done_task_is_noop_and_does_not_write`, `test_cli_done_and_noop_messages` | covered |
| FR-8 | `test_reopen_done_task`, `test_cli_reopen_and_noop_messages` | covered |
| FR-9 | `test_reopen_open_task_is_noop`, `test_cli_reopen_and_noop_messages` | covered |
| FR-10 | `test_delete_removes_task`, `test_cli_delete_then_list` | covered |
| FR-11 | `test_unknown_id_raises_and_changes_nothing`, `test_cli_unknown_id_exit_1_and_no_change`, `test_cli_invalid_id_exit_1_and_no_change` | covered |
| NFR-1 | `test_module_uses_only_standard_library`, `test_module_runs_as_python_m_todo_cli` | covered |
| NFR-2 | `test_title_is_stored_exactly`, `test_cli_title_with_spaces_punctuation_and_non_ascii_is_stored_exactly` | covered |
| NFR-3 | the exact-message and exit-code tests in the `test_cli_*` group | covered, wording only (see Gaps) |
| NFR-4 | `test_id_is_not_reused_after_deleting_newest_task`, `test_delete_keeps_next_id`, `test_cli_full_round_trip` | covered |

Gaps:

- NFR-3 asks for messages that a user can understand. The tests pin the exact wording of every message and the stream and exit code it uses, but whether the wording is clear is a human judgement that no test can make.
- Open questions from the requirements were settled by design decisions D-1 to D-4 in the architecture. The tests verify the implementation of those decisions (JSON persistence, rejected empty titles, separate invalid and unknown id messages, the command names). They do not verify that the decisions are what the product owner wanted, which is a human confirmation.
- Known limitations recorded in `artifacts/review.md` and not fixed: a title with invalid UTF-8 bytes produces a traceback and a leftover temporary file (finding 1), and a deeply nested storage file produces a traceback (finding 2). Neither has a test and neither is a stated requirement, so they do not change a requirement's status. A user can still hit them.
- Two simultaneous runs against one storage file are not coordinated and not tested, an accepted limitation in the architecture.
- Printing a non-ASCII title to a terminal that is not UTF-8 was not tested (review finding 7), so the exact-title tests prove storage and display only under UTF-8.

## Evidence

Evidence-ID: 50

Audit entry 50 is the `checks.run` record for this phase: exit code 0, 336 passed, 0 failed, 0 errors, with a recorded source digest of `f91239c3b6418037933708793774aded55dd7ebf848c3da405c7f0cd360717e2`.

## Verdict

Verdict: PASS

The checks passed (entry 50: 336 passed, 0 failed, 0 errors) and every requirement FR-1 to FR-11 and NFR-1 to NFR-4 is covered by passing tests. The gaps above are stated openly. None of them leaves a requirement without a passing test, and the two known limitations from the review are not stated requirements.
