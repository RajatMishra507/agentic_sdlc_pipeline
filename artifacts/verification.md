# Verification Report

## Commands Executed

1. `python3 orchestrator.py current` and `python3 orchestrator.py status`: confirmed that `review` is approved and `verify` is in progress.
2. `.venv/bin/python orchestrator.py run-checks`: the orchestrator's own check command, started with the project interpreter because the system `python3` has no `pytest` installed. The orchestrator runs `python -m pytest -q tests` with the interpreter that launches it.
3. `.venv/bin/python orchestrator.py audit --event checks.run --tail 1`: read the audit sequence number of the run (entry 85, event `checks.run`, phase `verify`).
4. `.venv/bin/python -m pytest -q tests/test_todo.py`: an extra read-only count for the sample application tests alone (148 passed). It is not the evidence for this report.

The run was repeated because the earlier run (entry 78, 2 failures) was invalidated by a human-authorized change to `orchestrator.py`, `sdlc/phases.json`, `docs/CONTRACT.md` and `tests/test_orchestrator.py`. No source file was changed after run 85.

## Results

`run-checks` recorded: exit code 0, 343 passed, 0 failed, 0 errors. The checks passed.

The two tests that failed in the earlier run (entry 78) now pass: `test_automatic_phases_cannot_be_approved_by_hand` and `test_verify_accepts_only_passing_unchanged_evidence`. Every phase now requires human approval, and `submit` returns `awaiting_approval` until a human approves it. All 148 tests in `tests/test_todo.py` also pass.

I did not edit code or tests in this phase; the only file written here is this report.

## Requirement Coverage

All requirement ids below are from `artifacts/requirements.md`. Coverage was assessed from the test names and assertions in `tests/test_todo.py`, which pass. Every requirement is covered by at least one passing test.

| Requirement | Covered by (tests in `tests/test_todo.py`) |
|-------------|--------------------------------------------|
| FR-1 add with free-text title | `test_cli_add_prints_id_title_and_status`, `test_cli_add_joins_words_with_single_spaces`, `test_title_is_stored_exactly` |
| FR-2 unique id, status `open` | `test_add_creates_open_task_with_unique_id`, `test_id_is_not_reused_after_deleting_newest_task`, `test_ids_stay_unique_across_sequential_instances` |
| FR-3 display id, title, status after add | `test_cli_add_prints_id_title_and_status` |
| FR-4 list in creation order with id, title, status | `test_list_is_in_creation_order`, `test_cli_list_order_and_columns`, `test_format_item_shows_id_status_title` |
| FR-5 empty-list message | `test_cli_empty_list_message`, `test_cli_missing_file_lists_empty_and_creates_nothing` |
| FR-6 complete open task | `test_complete_open_task`, `test_cli_done_and_noop_messages` |
| FR-7 complete done task is a no-op with message | `test_complete_done_task_is_noop_and_does_not_write`, `test_cli_done_and_noop_messages` |
| FR-8 reopen done task | `test_reopen_done_task`, `test_cli_reopen_and_noop_messages` |
| FR-9 reopen open task is a no-op with message | `test_reopen_open_task_is_noop`, `test_cli_reopen_and_noop_messages` |
| FR-10 delete task | `test_delete_removes_task`, `test_cli_delete_then_list` |
| FR-11 clear error and no change for invalid or unknown id | `test_unknown_id_raises_and_changes_nothing`, `test_cli_unknown_id_exit_1_and_no_change`, `test_cli_invalid_id_exit_1_and_no_change`, `test_cli_invalid_id_message_is_exact`, `test_parse_id_rejects_invalid_text`, `test_cli_negative_number_id_is_reported_as_invalid_id` |
| NFR-1 small Python command-line application | `test_module_uses_only_standard_library`, `test_module_runs_as_python_m_todo_cli`, `test_parser_defines_all_commands` |
| NFR-2 free-text titles | `test_title_is_stored_exactly`, `test_cli_title_with_spaces_punctuation_and_non_ascii_is_stored_exactly`, `test_cli_title_with_control_character_is_stored_raw_and_printed_escaped` |
| NFR-3 clear messages | exact-string assertions in `test_cli_add_prints_id_title_and_status`, `test_cli_done_and_noop_messages`, `test_cli_reopen_and_noop_messages`, `test_cli_unknown_id_exit_1_and_no_change`, `test_cli_invalid_id_message_is_exact`, `test_cli_empty_list_message` |
| NFR-4 ids stay unique after deletion | `test_id_is_not_reused_after_deleting_newest_task`, `test_delete_keeps_next_id`, `test_ids_stay_unique_across_sequential_instances` |

Acceptance criteria AC-1 to AC-13 map to the same tests through their FR and NFR references (for example AC-2 to the id reuse tests, AC-10 and AC-11 to the unknown and invalid id tests, AC-12 to `test_module_runs_as_python_m_todo_cli`, AC-13 to the non-ASCII and punctuation title tests).

Gaps and caveats, stated honestly:

- **Known defects from the review, not covered by tests.** `artifacts/review.md` reports that an invalid UTF-8 title raises an uncaught `UnicodeEncodeError` and leaves a temporary file, and that a deeply nested storage file raises an uncaught `RecursionError`. No test covers either case, so passing tests do not show that those failure paths are handled.
- **Untested claims.** No test checks that a symbolic link at the storage path is replaced, or that the saved file is owner-only.
- **Concurrency.** Overlapping runs can lose an update or reuse an id; this was accepted in the design and is not tested.

## Evidence

Evidence-ID: 85

Audit entry 85 is the `checks.run` record written by `run-checks` for this phase: exit code 0, 343 passed, 0 failed, 0 errors. The audit chain was reported INTACT when the entry was read.

## Verdict

Verdict: PASS

The checks passed (343 passed, 0 failed, 0 errors, entry 85) and every requirement has at least one passing test. The two robustness defects from the review remain unfixed and untested; they are not requirement gaps, but a human should decide whether to reopen `implementation` for them.
