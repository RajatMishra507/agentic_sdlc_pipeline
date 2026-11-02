---
name: verify
description: Verify the implementation with real evidence from orchestrator.py run-checks and map results to requirements. Use when writing artifacts/verification.md.
---

# Verification skill

## When to use

Writing `artifacts/verification.md`, or judging whether verification evidence is trustworthy.

## Method

1. Run `python3 orchestrator.py run-checks`. It executes the test suite, records pass, fail and error counts plus a digest of the source tree in the audit log, and returns non-zero on failure.
2. Read the audit entry: `python3 orchestrator.py audit --event checks.run --tail 1`. Cite its sequence number as `Evidence-ID: <n>`.
3. Build the coverage table: each requirement id, the tests that exercise it, and the result. Mark uncovered requirements as gaps.
4. Verdict is `PASS` only when the checks passed and there are no uncovered requirements.

## Rules

- Evidence is valid only if no source file changed after the run. Change code, run the checks again.
- Never hand-write results, counts, or Evidence-IDs.
- A failing run means `Verdict: FAIL`; do not submit, report to the human.
