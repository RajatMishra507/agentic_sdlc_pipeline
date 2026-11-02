# Agentic SDLC repository instructions

This repository runs an eight-phase SDLC pipeline controlled by `orchestrator.py`. The phase contract is `sdlc/phases.json`; read it with `python3 orchestrator.py describe <phase>`.

Phases, in order: requirements, architecture, design-review, planning, implementation, review, verify, pr. A phase can start only after its prerequisite is approved.

## Rules for every agent

- Work on one phase at a time. Run `python3 orchestrator.py current` first to see where the pipeline is.
- Start with `start <phase>`, finish with `submit <phase>`. Never edit `sdlc/`, `orchestrator.py`, `hooks/`, `tools/`, `docs/`, `.github/`, `.vscode/` or the orchestrator and guard tests. The guard hook blocks these, and attempts are recorded in the audit log.
- Never run `approve`, `reopen`, `init` or `authorize-pr`. Humans run them in their own terminal.
- Do not fake evidence. Confluence user stories come from the Atlassian MCP server, test results from `run-checks`, and the pull request from GitHub MCP. Cite audit sequence numbers exactly as found in `python3 orchestrator.py audit`.
- Do not commit secrets or read `.env` files. Do not push to main or master, force-push, or merge.
- Artifacts must not contain the uppercase words TODO, TBD, FIXME or XXX.

## Code conventions

- Python 3.11+, standard library for runtime code, type hints on public functions.
- Sample application: `todo/app.py` holds logic, `todo/cli.py` the command line, tests in `tests/test_todo.py`.
- Run tests with `python3 -m pytest -q`.
