# Changelog

## 0.1.0

- Orchestrator (`orchestrator.py`) with eight phases, prerequisites, human approval gate, artifact hashing, stale detection, reopen with archive, and a hash-chained audit log with state anchoring and interrupted-transition recovery.
- Phase contract in `sdlc/phases.json`.
- Security guard hook (`hooks/guard.py`): protected paths, per-phase write scopes, shell and git restrictions, secret and credential protection, MCP policy, fail-closed behavior.
- MCP evidence: guard records Atlassian Confluence and GitHub pull request calls; the orchestrator verifies them at submit. Pull request creation requires a human `authorize-pr` and is single use. Switched off by default via `integrations.mcp_evidence` in `sdlc/phases.json`.
- `run-checks` records real test results with a source digest for the verification phase.
- Eight agents, eight prompts, three skills, repository instructions, hook and MCP configuration.
- Sample `todo` application with tests.
- `tools/audit_repo.py` structure and content audit; contract and runbook documents.
