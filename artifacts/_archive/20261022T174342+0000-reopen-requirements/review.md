# Review Report

Review of the implementation phase against `artifacts/plan.md` and `artifacts/implementation.md`. No source file or test was modified. Probes ran in a temporary directory outside the repository.

## Scope

Read in full: `artifacts/plan.md`, `artifacts/implementation.md`, `todo/app.py`, `todo/cli.py` and `tests/test_todo.py`. `todo/app.py` was re-read after the notice that it had changed since submission, and its content matches what the implementation report describes.

Checks performed:

- Plan coverage: each of the 15 plan tasks was matched to code and to named tests, and each of AC-1 to AC-13 has at least one test.
- Test run: `python3 -m pytest -q` (using the project virtual environment) passes in full. `tests/test_todo.py` has 144 tests.
- Edge-case probes through `python3 -m todo.cli` in a temporary directory: an argument with an invalid UTF-8 byte, a 200000-level nested JSON file, and a title with a no-break space.
- Security scan of `todo/`: no `eval`, `exec`, `pickle`, `shell=True`, `subprocess` or `os.system` in runtime code. The only `subprocess` use is in the test that runs `python3 -m todo.cli`, with a fixed argument list and no shell.
- Design review conditions: finding 1 (long ids), finding 2 (escaping in every message) and finding 3 (dash-leading words) are each implemented and tested.

Plan conformance: tasks 1 to 14 are implemented as written, task 15 holds (no third-party import, `requirements.txt` unchanged). The deviations in the implementation report are accurate. The one that matters is dash-leading words, discussed in finding 4.

## Findings

1. **Severity: medium. `todo/app.py` lines 139 to 148 (`_save`). A title that cannot be encoded leaves a traceback and a stray temporary file.** On macOS and Linux, a command-line argument that contains invalid UTF-8 bytes reaches Python with lone surrogate characters. `todo add $'bad\xffbyte'` passes `add` validation, then `handle.write(payload)` at line 141 raises `UnicodeEncodeError`. That is a `ValueError`, not an `OSError`, so the `except OSError` at line 145 does not catch it. The result seen in the probe: an unhandled traceback (not the clear `error:` message with exit code 1 that NFR-3 and the architecture require), and a `.todo-XXXX.tmp` file left in the directory, which contradicts the plan's statement that a failed write removes the temporary file and the architecture's atomic-write rule. The stored data is not corrupted, because the target is never replaced and memory is not updated. No test covers it. Recommended fix: in `_save`, catch `UnicodeEncodeError` as well as `OSError` and remove the temporary file in both cases, or reject titles that cannot be encoded in `add` with a clear `TodoError`. Add a test that passes a lone surrogate title and checks for exit code 1, an `error:` message, no traceback and no leftover `.tmp` file.

2. **Severity: low. `todo/app.py` line 83 (`_load`). A deeply nested JSON file ends in a traceback.** A storage file that consists of 200000 opening brackets raises `RecursionError` inside `json.loads`. `RecursionError` is not a `ValueError` or `OSError`, so it escapes and the user sees a traceback instead of `error: cannot read ...`. The file is not modified. This needs a deliberately hostile or hand-built file, so the risk is small, but the design promises that a damaged file gives a `TodoError`. Recommended fix: add `RecursionError` to the exception tuple at line 84, and add a parametrised corrupt-file case for it.

3. **Severity: low. `todo/app.py` line 37 (`escape_text`). Non-ASCII spaces are shown as escapes.** `str.isprintable()` is false for the no-break space and other Unicode space separators, so a title containing U+00A0 is listed as `a\xa0b`. The stored title is exact, but the display is not "exactly as entered" for this class of character, and the architecture's documented exception for AC-13 only names control characters. Ordinary spaces, punctuation, accents, CJK text and emoji are unaffected, and the tests cover those. Recommended fix: either treat Unicode space separators (category `Zs`) as printable in `escape_text`, or extend the documented exception to say that non-ASCII space characters are also escaped. Add a test for the chosen behaviour.

4. **Severity: low. `todo/cli.py` lines 14 to 17 (`EPILOG`). The help text overstates the dash rule.** It says a word that starts with a dash "is read as an option and the command exits with code 2". The tests and the implementation report show this is not true for numbers: `done -3` exits 1 with an invalid id message, and `add -5 degrees` stores the title. Only option-like words (`-x`, `-urgent`) exit 2 without `--`. The behaviour is acceptable and pinned by tests (`test_cli_negative_number_id_is_reported_as_invalid_id`, `test_cli_add_negative_number_title_is_accepted`), but the help text is wrong for numbers. Recommended fix: reword the epilog to say that a word that looks like an option, such as `-urgent`, must follow `--`.

5. **Severity: low. `tests/test_todo.py`, `test_help_names_default_file_and_dash_rule`. The test is weak.** It asserts that the help output contains `todo.json`, `--` and `dash`, and `--` appears in nearly any help output, so it would pass even if the dash rule were removed. Recommended fix: assert on the full rule sentence, which also locks in the corrected wording from finding 4.

6. **Severity: low. `todo/app.py` lines 99 to 113 (`_load`). A hand-edited id of more than 18 digits cannot be used.** The loader accepts any positive integer id, but `parse_id` rejects more than 18 digits, so such a task is listed but can never be completed, reopened or deleted by id. Tasks created by the program always have small ids, so only a hand-edited file can reach this. Recommended fix: reject ids above the `MAX_ID_DIGITS` limit when loading, or note the limit in the architecture. No action is required for the requirements.

7. **Severity: low (informational). Standard output encoding.** Printing a non-ASCII title when the terminal or pipe uses a non-UTF-8 encoding (for example a locale set to `C` with Python's UTF-8 mode off) raises `UnicodeEncodeError` at the `print` call. Python 3.11 and later usually coerce the `C` locale to UTF-8, so this is rare, and it was not reproduced here. No fix is requested. It is recorded so that the verify phase does not treat the exact-title tests as proof for every environment.

What is correct and was checked:

- Each plan task is implemented, and each FR, NFR and AC has a passing test.
- Writes are atomic. The target is replaced only after the temporary file is written, flushed and synced, memory is updated only after a successful save, and a forced `os.replace` failure leaves the old file and no temporary file (`test_failed_replace_keeps_old_file_and_removes_temp`).
- A corrupt file is never overwritten, and all 20 corrupt-file cases check the bytes are unchanged.
- No-op commands do not write, which the tests prove by replacing `_save` with a function that fails the test.
- Ids are never reused, because `next_id` is persisted and only increases.
- Input validation is strict: ids are ASCII-only with a length cap, a 5000-digit id gives a clear error, and every id error and title is escaped before it reaches the terminal.
- The change is confined to `todo/app.py`, `todo/cli.py` and `tests/test_todo.py`, plus the phase artifact. No dependencies were added.

## Security Review

- **Dangerous calls:** none found. There is no `eval`, `exec`, `pickle`, `marshal`, `shell=True`, `os.system` or dynamic import in `todo/`. Parsing uses `json` only, and every field is type-checked on load, including the booleans-as-integers trap.
- **Injection:** titles and ids are never used to build commands or paths. The storage path comes only from the user's own `--file` option. Terminal escape sequences in titles, ids and file paths are made visible by `escape_text` in every output and error message, and tests check that standard output and standard error contain no raw escape character.
- **File handling:** `tempfile.mkstemp` creates an owner-only temporary file in the target directory, the write is flushed and synced, and `os.replace` makes the swap atomic. The permission and symbolic-link behaviour is stated in a code comment, as design review finding 6 asked. The one gap is finding 1, where an encoding error leaks the temporary file. That is a hygiene problem, since the file holds only the user's own task text, and it is not a data exposure.
- **Corrupt data:** handled by `TodoError`, except for the deep-nesting case in finding 2.
- **Denial of service:** a very long title or a very large file is limited only by memory and the command line, which the architecture accepted. The id length cap prevents the integer-conversion limit from being reached.
- **Secrets:** none in the changed files. No `.env` file was read.
- **Concurrency:** two simultaneous runs are not coordinated, an accepted limitation from the architecture.

## Verdict

Verdict: APPROVED_WITH_COMMENTS

No requirement or acceptance criterion fails, the data is never corrupted, and no security defect was found. Finding 1 is a real defect that I would fix before relying on the tool: a non-UTF-8 argument produces a traceback and leaves a temporary file behind. It does not block approval because it breaks no stated requirement and loses no data. If you want it fixed first, reopen implementation for findings 1 and 2, which are small changes with one test each. Findings 3 to 7 can be handled at your discretion, and findings 4 and 5 are best done together.
