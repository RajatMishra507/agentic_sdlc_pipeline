---
name: requirements
description: Turn Confluence user stories, fetched through the Atlassian MCP server, into verifiable requirements. Use when writing or checking artifacts/requirements.md.
---

# Requirements skill

## When to use

Writing `artifacts/requirements.md` in the requirements phase, or reviewing whether it is grounded in real Confluence content.

## Method

1. Fetch the source with the Atlassian MCP tools (search Confluence, then get the page). Read-only. If nothing is returned, stop and report; never substitute invented stories.
2. For each story record: id (US-n), who, what, why, and the page URL it came from.
3. Derive requirements:
   - Functional (FR-n): one verifiable behavior each, referencing its story id.
   - Non-functional (NFR-n): measurable (for example "list of 1000 items renders in under 1 second").
4. Write acceptance criteria as Given / When / Then, one or more per requirement.
5. List assumptions and open questions rather than guessing missing detail.
6. Evidence section: `Confluence-URL: <exact url from the MCP result>` and `Evidence-ID: <audit seq>`. Look up sequence numbers with `python3 orchestrator.py audit --event mcp.call`.

## Quality checks

- Every requirement traces to a story; every story to at least one requirement.
- No vague words without a measure ("fast", "easy", "robust").
- No uppercase TODO, TBD, FIXME, XXX; no secrets.
- `python3 orchestrator.py submit requirements` passes.
