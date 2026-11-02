# Runbook

All commands run from the repository root. Use the project virtual environment (`.venv/bin/python`) or any Python 3.11+ in place of `python3`.

## First-time setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q                 # all tests must pass
python3 tools/audit_repo.py                   # structure and content audit
python3 orchestrator.py init                  # once; creates sdlc/state.json and the audit log
```

In VS Code:

1. Open the folder. Confirm hooks are enabled: `.github/hooks/hooks.json` runs `hooks/guard.py` before and after every tool call.
2. MCP integrations are off by default (`integrations.mcp_evidence` is `false` in `sdlc/phases.json`). To use them, set it to `true`, then start the MCP servers from `.vscode/mcp.json`. `atlassian` opens a browser sign-in (OAuth). `github` also signs in through VS Code (OAuth); no token is written to the repository.
3. Select the phase agent in Copilot Chat, or run its prompt (`/requirements`, `/architecture`, and so on).

## Normal flow

```bash
python3 orchestrator.py current              # what is next
```

For each phase: run the agent (it runs `start`, writes the artifact, runs `submit`), then you review the artifact and approve in your own terminal:

```bash
python3 orchestrator.py approve <phase> --approver <your-github-username> --comment "reviewed"
# type the exact phrase it prints, e.g. APPROVE requirements
```

If you disagree: `python3 orchestrator.py reject <phase> --reason "why"` returns it to the agent.

Phases 5 and 7 (`implementation`, `verify`) approve themselves on a valid submit. Phase 6 (`review`) and phase 8 (`pr`) are where you check that work.

### Phase 1: requirements

Give the agent the Confluence page URL or search terms. After it runs, check `python3 orchestrator.py audit --event mcp.call` shows the Atlassian call, and that the stories in `artifacts/requirements.md` match the page. Approve only if they do.

### Phase 7: verify

The agent runs `python3 orchestrator.py run-checks`. If any source file changes afterwards, the evidence goes out of date; run it again.

### Phase 8: pull request

1. The agent writes `artifacts/pr.md` with `Repository:`, `Head:` and `Base:` lines and stops.
2. Read `pr.md`. Make sure the head branch is a feature branch. Then authorize exactly one pull request:
   ```bash
   python3 orchestrator.py authorize-pr --repo owner/name --head feature/todo --base main --approver <you>
   # type: AUTHORIZE PR owner/name feature/todo main
   ```
3. The agent pushes to the head branch, calls GitHub MCP `create_pull_request`, records `PR-URL` and `PR-Evidence-ID`, and runs `submit`.
4. You approve phase 8. Merge on GitHub yourself, after your normal review and CI.

If `pr.md` changes after authorization, the creation is blocked until you authorize again.

## Checks and diagnosis

| Command | Use |
|---------|-----|
| `python3 orchestrator.py status` | all phases |
| `python3 orchestrator.py validate` | order, artifacts, evidence, hashes; non-zero on problems |
| `python3 orchestrator.py revalidate` | re-hash artifacts; drift marks phases `stale` |
| `python3 orchestrator.py audit --tail 0` | full audit log and chain check |
| `python3 orchestrator.py audit --event guard.denied` | what the guard blocked |
| `python3 tools/audit_repo.py` | structure and content audit |

## Problems

**A phase is `stale`.** An approved or submitted artifact changed. Review the change; to continue, `python3 orchestrator.py reopen <phase> --reason "..."`. Later phases reset and their artifacts are archived under `artifacts/_archive/`.

**`state checksum mismatch` or `does not match the audit log`.** `sdlc/state.json` or the audit log was edited outside the orchestrator. Nothing was changed. Restore both files together: `git checkout -- sdlc/state.json sdlc/audit.log.jsonl` (or from a backup). Restoring only one will not work. Do not edit them by hand.

**`audit log integrity failure`.** An entry was edited or removed. Restore the log and state from git.

**`interrupted transition detected`.** The process stopped between the audit write and the state write. The next change discards the half-finished one and records `state.recovered`. Re-run the command that was interrupted.

**`state file is corrupted`.** Restore with git as above. To start over completely on a fresh clone: empty `sdlc/state.json` and `sdlc/audit.log.jsonl`, then `python3 orchestrator.py init`.

**The agent cannot write a file.** Check `audit --event guard.denied`; the reason names the rule. The usual cause is writing a file that belongs to another phase.

**No Confluence evidence.** The Atlassian server may not be signed in, or the hook may be disabled. Fix the connection and ask the agent to fetch the page again. Never type an Evidence-ID by hand; `submit` checks it.

**A hook does not run.** Check that hooks are enabled in VS Code and that `python3` is on the PATH of the hook's shell. A failing hook blocks tool calls (fail closed), which is intended.

**Tests fail in `run-checks`.** Fix the code through the implementation phase (`reopen implementation` if needed); do not edit evidence.
