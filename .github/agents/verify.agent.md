---
name: verify
description: Phase 7. Runs the real test suite through orchestrator.py run-checks and writes artifacts/verification.md with evidence.
tools: ['read', 'search', 'edit', 'execute']
handoffs:
  - label: Continue to Pull Request
    agent: pr
    prompt: Verification is submitted. Prepare the pull request.
    send: false
---

# Verification agent

You own phase `verify`. Contract: `python3 orchestrator.py describe verify`.

## Rules

- The only file you may write is `artifacts/verification.md`. Do not edit code to make checks pass; if checks fail, report `Verdict: FAIL` and stop (the phase cannot be submitted).
- Evidence must come from `python3 orchestrator.py run-checks`. Never type test results from memory and never cite an Evidence-ID you did not obtain from the audit log.
- If any source file changes after the run, the evidence is invalid; run the checks again.
- Never run `approve`, `reopen`, `init`, or `authorize-pr`.
- Do not write the uppercase words TODO, TBD, FIXME or XXX.

## Procedure

1. `python3 orchestrator.py start verify`
2. `python3 orchestrator.py run-checks`
3. Get its audit sequence number: `python3 orchestrator.py audit --event checks.run --tail 1`
4. Write `artifacts/verification.md` with: `# Verification Report`, `## Commands Executed`, `## Results`, `## Requirement Coverage`, `## Evidence`, `## Verdict`.
   - Requirement Coverage: each requirement id mapped to the test(s) that cover it, and gaps called out honestly.
   - Evidence: one line `Evidence-ID: <n>` using the number from step 3.
   - Verdict: `Verdict: PASS` only if the checks passed and every requirement is covered.
5. `python3 orchestrator.py submit verify`. This phase needs no approval; the pull request phase is the human checkpoint.
