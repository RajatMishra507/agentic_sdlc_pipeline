# Implementation Report

## Summary of Changes

The plan (`artifacts/plan.md`) was applied task by task. `todo/app.py`, `todo/cli.py` and `tests/test_todo.py` already existed from an earlier cycle, so each task first checked the existing behavior against the requirement and its tests, as the plan asked. The baseline (144 tests) passed, and every behavior in the architecture was confirmed. Only gaps were changed. Result: 148 tests in `tests/test_todo.py` pass.

Per task:

| Task | Result |
|------|--------|
| 1 Baseline and environment | Confirmed. 144 passed. The system `python3` (3.14.5) has no `pytest`; the project's `.venv` has pytest 9.1.1. `requirements.txt` needed no change (runtime dependencies: none; `pytest` is listed in `requirements-dev.txt`, which is protected). |
| 2 Id parsing and escaping | Confirmed. Existing tests cover whole numbers, `0`, `-1`, `1.5`, empty, Unicode digits, 19 and 5000 digits, control characters and shortening. |
| 3 Task model and add | Confirmed. Persisted `next_id`, status `open`, exact title storage, empty and whitespace-only titles rejected without writing. |
| 4 List and format | Confirmed. Creation order, copies, no write on list, `<id>  <status>  <title>`. |
| 5 Complete and reopen | Confirmed. Status changes, no-op returns `changed=False` without saving, unknown id leaves the file unchanged. |
| 6 Delete | Confirmed. Removes the task, keeps `next_id`, unknown id raises. |
| 7 Storage load, validation, atomic save | Confirmed behavior. Changed a code comment in `_save` to state that missing parent directories are created at every level, that an existing file's permissions are replaced, and that a symbolic link is replaced. |
| 8 CLI wiring and exact messages | Confirmed. Existing tests already compared the success and unknown-id messages as exact strings. Added an exact-string test for the invalid-id error. |
| 9 Dash-leading ids and titles | Confirmed. Help text states the `--` rule; tests pin `done -x` (exit 2), `done -- -x` (exit 1 with the invalid-id message), `-3` (exit 1), `add -urgent` (exit 2), `add -- -urgent` and `add -5 degrees` (accepted). This is the documented exception to AC-11. |
| 10 Display escaping | Confirmed. Added a note in the `escape_text` docstring that only printing escapes, so the AC-13 wording is narrowed for non-printable characters only. Added a test that a title with a control character is stored raw in memory and in the JSON file and printed escaped. |
| 11 Empty-title rule kept reversible | Confirmed. The rule is in one place, `TodoList.add`, with one test at the app layer and one at the CLI layer. |
| 12 Uniqueness limit | Changed. Added a `TodoList` docstring stating that ids stay unique across sequential runs and that concurrent writers are not supported. Added a test that separate instances never reuse an id, including after a delete. |
| 13 Postponed annotations guard | Changed. Added a test that `todo/app.py` imports `annotations` from `__future__`. No rename of `TodoList.list`. |
| 14 End to end and module entry point | Confirmed. Round trip, missing file, corrupt file, unwritable storage and `python3 -m todo.cli` subprocess tests pass. |
| 15 Coverage check and final run | Done. Every FR-1 to FR-11, NFR-1 to NFR-4 and AC-1 to AC-13 maps to at least one passing test in `tests/test_todo.py`. No requirement was left without a test. |

## Changed Files

- `todo/app.py`: comments and docstrings only (parent-directory creation and permission replacement in `_save`, escaping scope in `escape_text`, sequential uniqueness in `TodoList`). No logic changed.
- `tests/test_todo.py`: four new tests added.
- Not changed: `todo/cli.py`, `todo/__init__.py`, `requirements.txt`.

## Tests Added or Updated

Added to `tests/test_todo.py` (no existing test was changed, weakened or removed):

- `test_cli_invalid_id_message_is_exact`: the invalid-id error is exactly `error: invalid id 'abc': an id is a whole number such as 1` on stderr, exit 1.
- `test_cli_title_with_control_character_is_stored_raw_and_printed_escaped`: a title with `\x1b` is stored unchanged in memory and in the JSON file and printed as `\x1b`.
- `test_ids_stay_unique_across_sequential_instances`: three separate `TodoList` instances on one file, with a delete in between, never produce the same id.
- `test_app_uses_postponed_annotations`: `todo/app.py` imports `annotations` from `__future__`.

Results with the project's `.venv` interpreter:

- `tests/test_todo.py`: 148 passed (144 before this phase, 4 added).
- Full `tests/` directory: 338 passed, 2 failed. The failures are outside the files this phase may change; see the next section.

## Deviations from Plan

1. **Two protected orchestrator tests fail.** `tests/test_orchestrator.py::test_automatic_phases_cannot_be_approved_by_hand` and `tests/test_orchestrator.py::test_verify_accepts_only_passing_unchanged_evidence` expect `submit` for `implementation` and `verify` to return `approved`; they now get `awaiting_approval`. The cause is that `sdlc/phases.json` now has human approval for those phases (the status table shows `human`), while the tests still assume automatic approval. This is not a defect in `todo/`. I did not edit the tests or the contract, because both are protected. A human needs to decide whether to update those two tests to match the new contract or to revert the setting.
2. **Test interpreter.** Tests were run with `.venv/bin/python` because the system `python3` has no `pytest`. `orchestrator.py run-checks` runs `sys.executable -m pytest`, so the verify phase must be started with an interpreter that has `pytest` (for example `.venv/bin/python orchestrator.py run-checks`). No file change was needed for this.
3. **Plan task 1 conditional.** The plan allowed a `requirements.txt` change if a dependency was missing. None was needed, so it was left as is.
4. **Findings left to a human.** Design review findings 6 and 9, and the architecture text for findings 4 and 5, are wording in `artifacts/architecture.md`, which this phase cannot change. The code now behaves as the findings describe, and a decision entry for the display escaping (D-9) is still open for the architecture owner.
5. **No logic change was needed.** The existing code already met every requirement, so the work in `todo/` is documentation of behavior, and the extra tests pin it.
