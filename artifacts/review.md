# Review Report

## Scope

Reviewed the implementation phase output against `artifacts/plan.md` and `artifacts/implementation.md`:

- `todo/app.py` and `todo/cli.py` (read in full), and `todo/__init__.py` by listing.
- `tests/test_todo.py` (read in full; 148 tests).
- The full test suite, run read-only with the project interpreter (`.venv/bin/python -m pytest -q`): 338 passed, 2 failed (see finding 3). `tests/test_todo.py` alone: 148 passed.
- Two edge cases were probed with the CLI against throwaway temporary directories (findings 1 and 2). No repository file was modified.

Plan conformance: all 15 plan tasks are accounted for in the implementation report. The existing code already matched the architecture, so the phase changed only comments, docstrings and four tests. I confirmed in the source that the claimed behaviors are present: persisted `next_id`, exact title storage, no-op without a save, atomic save with a temporary file, validation of the storage file on load, ids restricted to ASCII digits with an 18 digit limit, and escaping on every output path. The four tests the report lists as added are present.

## Findings

1. **Severity: medium. File: `todo/app.py` lines 148-152 (`_save`).** A title that cannot be encoded as UTF-8 crashes the program with a Python traceback and leaves a temporary file behind.
   - Reproduction: on macOS, run `python3 -m todo.cli --file <path> add "$(printf 'bad\xffbyte')"`. The shell passes an invalid byte, Python represents it as a lone surrogate, and `handle.write(payload)` raises `UnicodeEncodeError`.
   - Effects: `UnicodeEncodeError` is a `ValueError`, but the handler at line 152 catches only `OSError`. The error is not converted to `TodoError`, so a traceback is printed. The cleanup `Path(tmp).unlink(...)` is inside that handler, so the file `.todo-<random>.tmp` stays in the storage directory (observed). This contradicts the architecture ("errors never include a stack trace", atomic save leaves no temporary file). The original list file is not damaged, because `os.replace` was never reached, so there is no data loss.
   - Recommended fix: in `_save`, catch `(OSError, UnicodeError)` (or `ValueError`) in the write block, and remove the temporary file in a `finally` or in that handler. Alternatively reject titles that cannot be encoded in `TodoList.add` with a clear `TodoError`. Add a test with a title containing `"\udcff"` that expects exit code 1, an `error:` line, no traceback, and no leftover temporary file.

2. **Severity: medium. File: `todo/app.py` line 90 (`_load`).** A storage file with extremely deep nesting crashes with a traceback.
   - Reproduction: a file containing 200000 `[` characters, then `python3 -m todo.cli --file <path> list`. `json.loads` raises `RecursionError`, which is not in `except (OSError, ValueError)`, so the program prints a traceback instead of `error: cannot read ...`.
   - Effects: the requirement for corrupt data handling (clear message, file untouched) is met for every case the tests cover, but not for this one. The file is not modified, so the impact is a crash on hostile or damaged input.
   - Recommended fix: add `RecursionError` to the exception tuple at line 90 and add a test with a deeply nested file expecting exit 1 and `error: cannot read`.

3. **Severity: high for the pipeline, not a defect in `todo/`. File: `tests/test_orchestrator.py` (protected).** Two tests fail: `test_automatic_phases_cannot_be_approved_by_hand` and `test_verify_accepts_only_passing_unchanged_evidence`. Both still expect `submit` on `implementation` and `verify` to return `approved`, but those phases now require human approval and return `awaiting_approval`. The implementation report discloses this correctly.
   - Effects: `orchestrator.py run-checks` runs the whole `tests` directory, so the verify phase cannot record a passing check while these two tests fail. The plan's definition of done (full suite passing through `run-checks`) is therefore not met yet.
   - Recommended fix: a human must either update these two tests to the new approval setting, or restore the old setting. This reviewer and the implementation agent cannot change protected files.

4. **Severity: low. File: `tests/test_todo.py`.** Several behaviors that the code comments and the architecture state have no test: that a symbolic link at the storage path is replaced and not followed, and that the saved file has owner-only permissions. A search of the test file found no test for either. Recommended fix: add one test for each, or soften the wording in the comments to what is verified.

5. **Severity: low. File: `todo/app.py` lines 30-48 (`escape_text`).** The display rule is sound, but the narrowing of AC-13 is recorded only in a docstring. The architecture still has no decision entry for it. This was raised in the design review and is a human-owned document. No code change is needed.

6. **Severity: low. File: `artifacts/implementation.md`, Summary of Changes.** The report says every behavior in the architecture was confirmed, which findings 1 and 2 show was not fully accurate for failure paths. The report is otherwise accurate and honest about the two failing orchestrator tests. Recommended fix: none required; the next implementation report should say which failure paths were exercised.

## Security Review

- **Dangerous calls:** a search of `todo/` found no `eval`, `exec`, `shell=True`, `pickle`, `subprocess`, `os.system`, `input` or environment access. The runtime uses only the standard library, and a test enforces that.
- **Deserialization:** only `json.loads` is used, followed by strict type and range checks (booleans rejected as ints, versions, unique ids, `next_id` greater than every id). Finding 2 is the one gap: very deep nesting is not caught.
- **Input handling:** ids match ASCII digits only, at most 18 digits, and at least 1. Titles are stored as is and escaped on every output path, including error messages and the storage path, which blocks terminal escape injection. Echoed ids are shortened to 40 characters.
- **File handling:** writes use a temporary file created with `mkstemp` (owner-only), `fsync`, and `os.replace`, so a crash cannot leave a half-written list. In-memory state changes only after a successful save. Gaps: the temporary file leak in finding 1, and the untested symbolic link and permission claims in finding 4.
- **Secrets:** none found in `todo/` or the tests. No network access.
- **Path handling:** the `--file` path is chosen by the local user and is used as given; missing parent directories are created. This is acceptable for a single-user command-line tool and is documented in the code.
- **Concurrency:** no locking; two overlapping runs can lose an update or reuse an id. The limit is documented in the code and was accepted in the design (D-5).

No injection, secret exposure or privilege issue was found. Findings 1 and 2 are robustness defects that end in a crash, not in data loss or code execution.

## Verdict

Verdict: APPROVED_WITH_COMMENTS

The implementation meets every functional requirement and the tests for them pass. Two error-handling gaps (findings 1 and 2) are real and should be fixed, because they break the documented promise of clear errors without tracebacks and clean temporary files. I judged them as comments, not as blockers, because the original data is never damaged and no security impact exists; the human may instead reopen the implementation phase to fix them before verification. Finding 3 must be resolved by a human before the verify phase can pass.
