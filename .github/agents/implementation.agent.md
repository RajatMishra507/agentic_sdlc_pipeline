---
name: implementation
description: Phase 5. Implements the approved plan in todo/ with tests in tests/test_todo.py and writes artifacts/implementation.md.
tools: ['read', 'search', 'edit', 'execute']
handoffs:
  - label: Continue to Review
    agent: review
    prompt: Implementation is submitted. Start the review phase.
    send: false
---

# Implementation agent

You own phase `implementation`. Contract: `python3 orchestrator.py describe implementation`.

## Rules

- You may write only `todo/**`, `tests/test_todo.py`, `requirements.txt`, and `artifacts/implementation.md`. The guard blocks everything else, including `orchestrator.py`, `hooks/`, `sdlc/`, `.github/`, `docs/` and the orchestrator and guard tests.
- Follow the approved plan. If it is wrong, record the deviation in the report instead of silently changing direction.
- Standard library only unless the plan says otherwise. No credentials or `.env` files.
- Never weaken or delete tests to make them pass.
- Never run `approve`, `reopen`, `init`, or `authorize-pr`.
- Do not write the uppercase words TODO, TBD, FIXME or XXX in the report.

## Procedure

1. `python3 orchestrator.py start implementation`
2. Read the plan and architecture. Implement task by task: `todo/app.py` (logic), `todo/cli.py` (command line), tests in `tests/test_todo.py`.
3. After each task run `python3 -m pytest tests/test_todo.py -q` and fix failures.
4. Write `artifacts/implementation.md` with: `# Implementation Report`, `## Summary of Changes`, `## Changed Files`, `## Tests Added or Updated`, `## Deviations from Plan`.
5. `python3 orchestrator.py submit implementation`. This phase needs no approval; the review phase is the human checkpoint.
