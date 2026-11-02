# Pull Request

## Title

Add command-line Todo List application with tests

## Description

Adds a small, standard-library-only Python command-line Todo List application and its test suite, built from the Confluence user story "Todo List User Story" (US-1).

What the application does (requirements FR-1 to FR-11, NFR-1 to NFR-4, acceptance criteria AC-1 to AC-13):

- Add a task with a free-text title; each task gets a unique id and starts as `open`; the id, title and status are shown.
- List tasks in creation order, with a clear message when the list is empty.
- Complete and reopen tasks by id; repeating either action prints a no-op message and changes nothing.
- Delete a task by id; ids are never reused, including after deletions.
- An invalid or unknown id prints a clear error and changes nothing.

Files in this pull request:

- `todo/__init__.py`, `todo/app.py`, `todo/cli.py`: the application. Logic is in `app.py`, the command line is in `cli.py`.
- `tests/test_todo.py`: 148 tests covering every requirement.
- `requirements.txt`: runtime dependencies (none beyond the standard library).

Not included: the SDLC pipeline files (`sdlc/`, `orchestrator.py`, `hooks/`, `tools/`, `docs/`, `.github/`), the phase artifacts, and the orchestrator and guard tests.

## Linked Work Items

- Confluence: https://rbitestuserrj.atlassian.net/wiki/spaces/~71202025eaf9215838446398153749e55e74f1/pages/393233/Todo+List+User+Story
- Requirement ids from `artifacts/requirements.md`: US-1, FR-1 to FR-11, NFR-1 to NFR-4, AC-1 to AC-13.

## Verification Summary

From `artifacts/verification.md`:

- `python orchestrator.py run-checks` recorded audit entry 85: exit code 0, 343 passed, 0 failed, 0 errors. That run covers the whole `tests/` directory; 148 of those tests are in `tests/test_todo.py`, which is the test file in this pull request.
- Every requirement (FR, NFR and AC) maps to at least one passing test in `tests/test_todo.py`.
- Verdict: PASS, approved by a human.

Known limitations, reported honestly in the review and verification artifacts and not fixed here:

- A title that is not valid UTF-8 raises an uncaught `UnicodeEncodeError` and can leave a temporary file behind.
- A deeply nested storage file raises an uncaught `RecursionError`.
- Concurrent runs can lose an update or reuse an id; this was accepted in the design.

## Reviewer Checklist

- [ ] The change set contains only the application, its tests and `requirements.txt`.
- [ ] Each requirement in the linked Confluence story is met and has a passing test.
- [ ] `python3 -m pytest -q tests/test_todo.py` passes on the branch.
- [ ] The two known limitations above are acceptable or tracked separately.
- [ ] No secrets, credentials or `.env` files are present.
- [ ] A human reviews, approves and merges; the pipeline does not.

## Repository and Branches

Repository: RajatMishra507/agentic_sdlc_pipeline
Head: feature/todo-cli-20261029060347-77b34c
Base: main

## Pull Request Record

PR-URL: https://github.com/RajatMishra507/agentic_sdlc_pipeline/pull/2
PR-Evidence-ID: 115