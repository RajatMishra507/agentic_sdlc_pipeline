# Agentic SDLC Capstone

An eight-phase software delivery pipeline driven by specialized GitHub Copilot agents, with human approval gates, a tamper-evident audit log, a security guard hook, and two real integrations: the Atlassian Confluence MCP server (requirements) and the GitHub MCP server (pull request).

```
requirements -> architecture -> design-review -> planning -> implementation -> review -> verify -> pr
```

Each phase has one agent, one output file in `artifacts/`, and a prerequisite that must be approved first. Agents cannot approve their own work, change governance files, or create a pull request without a human `authorize-pr`.

## Layout

```
orchestrator.py            engine and CLI (all orchestration logic)
sdlc/phases.json           phase contract (outputs, sections, evidence, protected paths)
sdlc/state.json            current state, checksummed and anchored to the audit log
sdlc/audit.log.jsonl       append-only hash-chained audit log
hooks/guard.py             preToolUse security guard and postToolUse MCP evidence recorder
.github/hooks/hooks.json   registers the guard
.github/agents/            the eight agents
.github/prompts/           one prompt per phase
.github/skills/            requirements, verify, pr skills
.github/copilot-instructions.md
.vscode/mcp.json           Atlassian and GitHub MCP servers
artifacts/                 phase outputs (written by agents)
todo/                      sample application the agents build (app.py logic, cli.py command line)
tests/                     orchestrator, guard, and todo tests
tools/audit_repo.py        structure and content audit
docs/CONTRACT.md           guarantees, roles, limits
docs/RUNBOOK.md            operating instructions and recovery
```

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
python3 tools/audit_repo.py
python3 orchestrator.py init        # once, in your own terminal
python3 orchestrator.py current
```

Then run the first prompt in Copilot Chat (`/requirements`) with a Confluence page URL. See [docs/RUNBOOK.md](docs/RUNBOOK.md) for the full flow and [docs/CONTRACT.md](docs/CONTRACT.md) for what is guaranteed and what is not.

## Commands

`init`, `status`, `current`, `describe <phase>`, `start <phase>`, `submit <phase>`, `approve <phase> --approver <you>`, `reject <phase> --reason <why>`, `reopen <phase> --reason <why>`, `revalidate [phase]`, `validate`, `run-checks`, `authorize-pr --repo --head --base --approver`, `audit [--tail N] [--event E]`. Add `--json` for machine-readable output. `init`, `approve`, `reopen` and `authorize-pr` need a human at an interactive terminal.

## How the integrations are checked

Copilot calls the MCP tools, not Python. (MCP evidence is currently switched off: `integrations.mcp_evidence` is `false` in `sdlc/phases.json`, so only the description below applies once a human sets it to `true`.) The guard hook records each Atlassian and GitHub pull request tool result in the audit log, and the orchestrator checks the artifact's `Evidence-ID` against it at `submit`. No evidence, no submit. Verification evidence comes from `run-checks`, which runs the real test suite. Details and limits are in the contract.

## Requirements

Python 3.11 or newer. The runtime uses only the standard library. Tests need `pytest` (`requirements-dev.txt`).
