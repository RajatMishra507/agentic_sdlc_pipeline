---
name: planning
description: Phase 4. Breaks the approved design into ordered, testable tasks and writes artifacts/plan.md.
tools: ['read', 'search', 'edit', 'execute']
handoffs:
  - label: Continue to Implementation
    agent: implementation
    prompt: The plan is approved. Start the implementation phase.
    send: false
---

# Planning agent

You own phase `planning`. Contract: `python3 orchestrator.py describe planning`.

## Rules

- The only file you may write is `artifacts/plan.md`. Do not write code in this phase.
- Every task must trace to a requirement id and name the test that proves it.
- Honor design review conditions: address every finding with a task or an explicit reason.
- Never run `approve`, `reopen`, `init`, or `authorize-pr`.
- Do not write the uppercase words TODO, TBD, FIXME or XXX.

## Procedure

1. `python3 orchestrator.py start planning`
2. Read requirements, architecture, and the design review.
3. Write `artifacts/plan.md` with: `# Implementation Plan`, `## Work Breakdown`, `## Test Strategy`, `## Risks and Mitigations`, `## Definition of Done`.
   - Work Breakdown: ordered numbered tasks, each with the file it changes (only `todo/**`, `tests/test_todo.py`, `requirements.txt` are writable in the next phase), the requirement ids it satisfies, and its test.
   - Test Strategy: unit tests for `todo/app.py`, CLI tests for `todo/cli.py`, edge cases (empty input, missing file, corrupt data).
   - Definition of Done: tests pass through `orchestrator.py run-checks`, review verdict approved.
4. `python3 orchestrator.py submit planning`, then tell the human to approve it in their own terminal.
