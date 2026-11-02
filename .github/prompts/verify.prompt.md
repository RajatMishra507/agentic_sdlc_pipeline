---
description: Run phase 7 (Verification). Run the real checks via orchestrator.py run-checks and write artifacts/verification.md.
agent: verify
---
Run the verification phase.

Check with `python3 orchestrator.py current` that the review is approved, then run `python3 orchestrator.py run-checks`, cite its audit sequence number, and write the report. If the checks fail, report the failure and stop.
