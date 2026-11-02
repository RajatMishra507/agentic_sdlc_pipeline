# Contract

This document defines what the pipeline guarantees, who may do what, and where the guarantees stop. The machine-readable contract is `sdlc/phases.json`; `python3 orchestrator.py describe <phase>` prints it.

## Phases

| # | Phase | Agent | Output | Prerequisite | Approval | Evidence |
|---|-------|-------|--------|--------------|----------|----------|
| 1 | requirements | requirements | `artifacts/requirements.md` | none | human | Confluence MCP call |
| 2 | architecture | architecture | `artifacts/architecture.md` | requirements | human | none |
| 3 | design-review | design-review | `artifacts/design-review.md` | architecture | human | none |
| 4 | planning | planning | `artifacts/plan.md` | design-review | human | none |
| 5 | implementation | implementation | `artifacts/implementation.md` and code | planning | human | none |
| 6 | review | review | `artifacts/review.md` | implementation | human | none |
| 7 | verify | verify | `artifacts/verification.md` | review | human | `run-checks` result |
| 8 | pr | pr | `artifacts/pr.md` | verify | human | GitHub MCP call |

Every phase requires explicit human approval; no phase is approved automatically on submit. A successful `submit` always leaves the phase `awaiting_approval`, and only `approve` (human, interactive terminal) records the approval, with method `human-confirmation`.

A phase starts only when every prerequisite is `approved`. A phase moves `not_started -> in_progress -> awaiting_approval -> approved`. `stale` means an approved or submitted artifact changed on disk; a human must `reopen` it.

## Roles

| Action | Agent | Human |
|--------|-------|-------|
| `status`, `current`, `describe`, `validate`, `audit`, `revalidate` | yes | yes |
| `start`, `submit`, `reject`, `run-checks` | yes | yes |
| `init`, `approve`, `reopen`, `authorize-pr` | no | yes, in an interactive terminal |
| Write artifacts and code | only the active phase's own files | yes |
| Merge a pull request | no | yes |

Human-only commands ask for an exact typed phrase (`APPROVE <phase>`, `REOPEN <phase>`, `AUTHORIZE PR <repo> <head> <base>`) on a TTY. Without a TTY they refuse, so scripts and agents cannot confirm. Approver names that look automated (copilot, bot, agent, gpt, claude and similar) are refused.

## Integrity guarantees

- Every state change writes a hash-chained audit entry (`sdlc/audit.log.jsonl`) holding the state checksum before and after, then writes `sdlc/state.json` atomically.
- On every load the orchestrator verifies the audit chain, the state checksum, and that the state matches the last audit anchor. A hand-edited state file or audit entry stops the pipeline with an explanation; nothing is repaired silently.
- A crash between the audit write and the state write is recognized as an interrupted transition and discarded at the next change (event `state.recovered`).
- Approval binds to the exact artifact hashes. An artifact changed after submission cannot be approved.
- Artifacts must contain all required sections, meet minimum size, and contain no placeholders (uppercase TODO, TBD, FIXME, XXX) or secrets.
- Reopening a phase resets later phases and copies their artifacts to `artifacts/_archive/`; nothing is deleted without a copy.

## Mandatory integrations and evidence

**Current state: MCP evidence is switched off.** `sdlc/phases.json` ships with `"integrations": {"mcp_evidence": false}`. While off, `requirements` and `pr` need only a valid artifact and human approval; the Confluence/PR evidence checks, the `Confluence-URL`/`Evidence-ID`/`Repository`/`Head`/`Base` patterns and the `## Evidence`/`## Pull Request Record` sections (`mcp_patterns`, `mcp_sections`) are not enforced; the guard records no `mcp.call` entries; `authorize-pr` is refused and `create_pull_request` is denied. Verification evidence from `run-checks` is not MCP and stays enforced. Set the flag to `true` (a human edit; the file is protected from agents) to turn everything below on.

Copilot calls MCP tools; Python cannot. So the guard hook records what happened, and the orchestrator verifies that record.

1. **Atlassian Confluence MCP.** The `postToolUse` hook appends an `mcp.call` audit entry for every Atlassian/Confluence tool result: tool name, error flag, result length, URLs found in the result. Page content is not stored. `requirements.md` must cite `Evidence-ID: <seq>` and `Confluence-URL: <url>`. `submit` accepts it only if the entry exists, is a Confluence call, came after the phase started, was not an error, returned at least 100 characters, and its result contained the cited URL.
2. **GitHub MCP.** `create_pull_request` is blocked by the `preToolUse` hook unless the `pr` phase is in progress, a human ran `authorize-pr` for exactly that repository, head, and base, `pr.md` is unchanged since, and no earlier creation succeeded (one authorization, one PR). The hook then records the call. `pr.md` must cite `PR-URL` and `PR-Evidence-ID`; `submit` checks them against that entry (repository, branches, content digest, URL). Branch writes (`create_branch`, `push_files`) are allowed only on the authorized head branch after authorization. Merge, delete, fork, force-push, and other GitHub writes are denied. Atlassian write tools are denied.
3. **Verification.** `orchestrator.py run-checks` runs the real test suite and records exit code, counts, and a digest of the source tree. `verification.md` must cite its `Evidence-ID`, and the digest must still equal the current source tree at `submit`.

## Guard policy (`hooks/guard.py`)

Denied: writes outside the repository; writes to protected paths (`sdlc/`, `orchestrator.py`, `hooks/`, `tools/`, `docs/`, `.github/`, `.vscode/`, `.git/`, the orchestrator and guard tests, project config); artifact writes outside the active phase's own output; code writes outside the active phase's `write_globs`; reading or writing credential files (`.env`, keys); secrets in content; `approve`, `reopen`, `init`, `authorize-pr`; driving the orchestrator through inline Python; force or hard git operations, `--no-verify`, pushes to main or master, `gh pr merge`, `sudo`, broad `rm -rf`, piping downloads into a shell. A malformed event or any internal error is denied (fail closed). Each denial is audited without tool arguments.

## Limits

- The guard is a guardrail for cooperative agents, not a sandbox. Shell command analysis is pattern based and can be evaded by a determined agent (for example through an encoded command). The human gates (`approve`, `reopen`, `authorize-pr`) do not rely on the guard: they need a TTY.
- A hook that times out is skipped by the host (fail open). The guard is fast and uses a 10 second limit.
- Evidence proves that a call was made and what shape it returned, not that a page's content was interpreted correctly. The human approval of `requirements.md` is where that is judged.
- Anyone with write access to the repository can edit `sdlc/` and the hooks, and can rewrite the whole audit log consistently. Git history and branch protection are the backstop.
- Live Confluence and GitHub runs need the human's own sign-in; none was made while building this repository.
