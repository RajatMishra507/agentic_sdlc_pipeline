---
description: Run phase 8 (Pull Request). Prepare artifacts/pr.md and create the PR via GitHub MCP only after human authorization.
agent: pr
---
Run the pull request phase (Stage A: feature branch and pull request creation).

Repository and base branch: ${input:target:owner/name, base branch}

Generate a unique feature branch name for the head, prepare `artifacts/pr.md`, then stop and ask me to run `authorize-pr` myself with the exact command. Create the feature branch and the pull request through GitHub MCP only after the authorization is recorded. Do not merge, approve, or review the pull request.
