---
name: pr
description: Prepare and create an authorized pull request through the GitHub MCP server, with evidence. Use when writing artifacts/pr.md or opening the PR.
---

# Pull request skill

## When to use

The pull request phase (Stage A): choosing a unique feature branch, drafting `artifacts/pr.md`, and creating the branch and the PR after human authorization.

## Method

1. Generate the head branch: `feature/<short-slug>-<UTC yyyymmddHHMMSS>-<6 random hex>`. Take the timestamp and hex from the shell. Check with `list_branches` (read-only) that it does not exist. It must be a feature branch, never `main` or `master`, and different from the base. Do not create it yet.
2. Draft `artifacts/pr.md`: Title (imperative, under 72 characters), Description (what and why, tied to requirement ids), Linked Work Items (Confluence URLs), Verification Summary (truthful summary of `artifacts/verification.md`), Reviewer Checklist.
3. Declare the target on separate lines: `Repository: owner/name`, `Head: <generated branch>`, `Base: <branch>`.
4. Pull Request Record starts as `Status: awaiting human authorization`.
5. Stop. The human runs `authorize-pr` for exactly that repository, head, and base. It binds the authorization to a digest of the document above the record heading. Give the human the exact command and wait for confirmation.
6. After authorization: GitHub MCP `create_branch` from the base onto the authorized head, then `push_files` on the head only (the files listed in `artifacts/implementation.md`; never `artifacts/pr.md`, `sdlc/`, or credential files), then `create_pull_request` with the authorized arguments.
7. Record `PR-URL: <url from the result>` and `PR-Evidence-ID: <audit seq from audit --event mcp.call>` in the record section, then submit the phase.

## Rules

- One authorization allows one pull request and one head branch name. If the branch already exists or the head must change, the human must authorize again.
- Use GitHub MCP only for branch and pull request creation; no `gh` and no `git push`.
- Never merge, approve, review, close, delete, or force-push. Never touch main or master.
- If pr.md content above the record changes after authorization, the human must authorize again.
- Never include tokens or other secrets in the PR text.
- Stage B is out of scope; do not act after the pull request is created.
