# Design Review

Independent critique of `artifacts/architecture.md` against `artifacts/requirements.md`. Neither document was edited. Items that need a change are reported here for the planning and implementation phases, or for the human to send back to architecture.

## Scope Reviewed

- `artifacts/requirements.md`: US-1, FR-1 to FR-11, NFR-1 to NFR-4, AC-1 to AC-13, and the four open questions.
- `artifacts/architecture.md`: context, component split (`todo/app.py`, `todo/cli.py`, JSON storage file), storage format, function signatures, command and exit-code tables, security considerations, decisions D-1 to D-9, and the traceability table.
- Existing sample code in `todo/app.py` and `todo/cli.py`, read only to check the architecture's list of gaps.

Checks performed:

- Every FR, NFR and AC is covered. Each FR and NFR appears in the traceability table with a named component, and the AC-to-requirement mapping is complete. No requirement is missing.
- Interfaces are consistent. The `TodoList` signatures, the command table, the exit-code table and the storage format agree with each other. `complete` and `reopen` return `(item, changed)`, which the no-op messages in the CLI table rely on. `delete` leaves `next_id` untouched, which NFR-4 needs.
- The gap table matches the sample code. All seven listed gaps are real. I found no gap that the table omits, except those raised in the findings below.
- The four open questions in the requirements are answered by D-1 to D-4 and are marked for human confirmation.

## Findings

1. **Severity: medium. Component: `parse_id` (FR-11, AC-10, AC-11).** The design says `parse_id` accepts "ASCII digits" and then converts the text to an integer. Python 3.11 and later raises `ValueError` when an integer string has more than 4300 digits. A very long all-digit id would escape as an unhandled exception and print a stack trace, which contradicts "a clear error" and the rule that `TodoError` is the only user-facing failure. Two related traps: `str.isdigit()` accepts non-ASCII digits, and a regular expression ending in `$` accepts a trailing newline. Recommended change: state that `parse_id` uses a full match on `[0-9]+` with a maximum length (for example 18 digits), and that anything longer is reported as an invalid id. Add a test for a 5000-digit id.

2. **Severity: medium. Component: error messages and `format_item` (NFR-3, security).** The Security section makes titles safe for the terminal through `format_item`, but `parse_id` messages "name the bad value", so they echo raw user input, and the unknown-id and file-error messages may also echo user text (the `--file` path). An id argument containing an escape sequence would then reach the terminal unescaped, which defeats the purpose of the escaping rule. Recommended change: require one shared escaping helper to be applied to every user-supplied string that appears in any output, error messages included, and test it with an escape character in an id.

3. **Severity: medium. Component: `add` command and `argparse` (FR-1, NFR-2, AC-13).** Titles are free text, but `argparse` treats a leading `-` as an option. `todo add -urgent` or a title such as `-5 degrees` fails with a usage error and exit code 2, and nothing is added. The same applies to ids that start with a dash, such as `-x`, which gives exit code 2 instead of the exit code 1 and the "invalid id" message that AC-11 and the exit-code table imply. Recommended change: document that a leading-dash title must follow `--`, and state in the exit-code table that dash-leading ids are the one case that reports exit 2. Alternatively, define the commands so these tokens are collected as plain text. Add tests for both cases so the behaviour is deliberate.

4. **Severity: low. Component: `format_item` (NFR-2, AC-13).** AC-13 says the title is displayed "exactly as entered". The design escapes control characters, so a title with a tab or newline is not displayed exactly. This is a sound security and layout choice, and the AC example (spaces, punctuation, non-ASCII) is unaffected. The deviation is not stated against NFR-2 in the traceability table. Recommended change: record the exception in the NFR-2 row, and test that ordinary and non-ASCII text round-trips unchanged while a control character is shown as an escape.

5. **Severity: low. Component: storage format (`version`).** The file carries `"version": 1`, but the design never says what happens with a different or missing version. Recommended change: state that any value other than 1 is rejected with a `TodoError`, and test it, so the field is not decorative. Also state that booleans are rejected for `id` and `next_id` (in Python, `true` passes an integer check), since the load check is the only defence against a hand-edited file.

6. **Severity: low. Component: `_save` and the storage path (security, file handling).** The atomic write uses `tempfile.mkstemp`, which creates the file with owner-only permissions, and `os.replace` then swaps it over the target. An existing file with different permissions silently becomes owner-only, and a symbolic link used as the storage path is replaced by a regular file instead of being followed. Both are acceptable for a single-user tool, but neither is stated. Recommended change: state the chosen behaviour in the architecture or in the implementation notes, and do not promise that permissions are preserved.

7. **Severity: low. Component: default storage location (FR-4, usability).** The default file is `todo.json` in the current directory, so running the tool from a different directory shows a different, possibly empty list with no warning. This is a user-surprise risk, not a requirement failure. Recommended change: mention it in the usage text (`--help` states the default file) and consider listing `todo.json` in the repository ignore file so test runs do not commit data.

8. **Severity: low. Component: `TodoList.list` (D-7 testability).** "Returns a copy of the items" is ambiguous. A shallow copy still shares the mutable `Item` objects, so a caller could change a status without saving. Also, a method named `list` shadows the built-in inside the class, which is fine at runtime with postponed annotations but easy to get wrong. Recommended change: return a new list of new `Item` objects (or make `Item` frozen and replace it on change), and keep `from __future__ import annotations` in `todo/app.py`.

9. **Severity: low. Component: test approach (NFR-3).** NFR-3 requires messages that are clear to a user, and the traceability table says "tested", but the architecture does not describe how tests check message wording or exit codes. Recommended change: have the planning phase add a task that asserts on exact messages, streams (standard output for success, standard error for errors) and exit codes through `main(argv)`, using a temporary storage file.

No finding is rated high. The design is implementable as written, and none of the problems above requires the requirements to change.

## Risks

- **Open questions answered by the design.** D-1 (JSON persistence), D-2 (empty titles rejected), D-3 (separate invalid and unknown id messages) and D-4 (command names, including renaming `remove` to `delete`) settle questions the Confluence story left open. If the product owner disagrees with any of them, the affected tests and messages must be reworked. These need explicit human confirmation at approval time.
- **Silent break of existing data.** The new file format is not compatible with files written by the sample (`done` boolean, no `next_id`). The design chooses to reject them and not migrate. Anyone with a `todo.json` from the sample will see an error on first use. The risk is small because the sample has no released data, but the error message should say what to do.
- **Unhandled-exception paths.** Findings 1 and 3 are the places where a user can still reach a stack trace or an unexpected exit code. They are cheap to close now and awkward to discover late.
- **Concurrent runs.** Two overlapping runs can lose an update. This was already accepted in the architecture and is repeated here only so planning does not treat it as covered.
- **Scope creep in security handling.** Escaping control characters is more than the requirements ask. It is reasonable, but it must be applied consistently (finding 2), otherwise it adds complexity without the protection it promises.

## Verdict

Verdict: APPROVED_WITH_CONDITIONS

Conditions for planning and implementation to carry forward (findings 1, 2 and 3 are mandatory, the rest should each get a task or an explicit reason for not doing it):

1. `parse_id` uses a full match on `[0-9]+` with a length cap and never lets `ValueError` escape.
2. All user-supplied text in any output, error messages included, passes through the same escaping helper.
3. The behaviour of titles and ids that begin with a dash is documented and tested, with the exit code stated.
4. The human confirms decisions D-1 to D-4 when approving.
