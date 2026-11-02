#!/usr/bin/env python3
"""Audit the repository against the mandated structure and wiring rules.

  python3 tools/audit_repo.py --structure   # exact tree only (no content checks)
  python3 tools/audit_repo.py               # structure + content/wiring checks

Exit codes: 0 = clean, 1 = findings, 2 = usage error.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

AGENTS = ("requirements", "architecture", "design-review", "planning", "implementation", "review", "verify", "pr")
SKILLS = ("requirements", "verify", "pr")

# EXPECTED_FILES: tuple[str, ...] = (
#     ".vscode/mcp.json",
#     *(f".github/agents/{a}.agent.md" for a in AGENTS),
#     *(f".github/prompts/{a}.prompt.md" for a in AGENTS),
#     *(f".github/skills/{s}/SKILL.md" for s in SKILLS),
EXPECTED_FILES: tuple[str, ...] = (
    ".vscode/mcp.json",
    *(f".github/agents/{a}.agent.md" for a in AGENTS),
    ".github/agents/orchestrator.agent.md",
    *(f".github/prompts/{a}.prompt.md" for a in AGENTS),
    ".github/prompts/orchestrator.prompt.md",
    *(f".github/skills/{s}/SKILL.md" for s in SKILLS),
    ".github/hooks/hooks.json",
    ".github/copilot-instructions.md",
    "hooks/guard.py",
    "sdlc/phases.json",
    "sdlc/state.json",
    "sdlc/audit.log.jsonl",
    "docs/CONTRACT.md",
    "docs/RUNBOOK.md",
    "tests/test_orchestrator.py",
    "tests/test_guard.py",
    "tests/test_todo.py",
    "todo/__init__.py",
    "todo/app.py",
    "todo/cli.py",
    "tools/audit_repo.py",
    "orchestrator.py",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    ".gitignore",
    "README.md",
    "CHANGELOG.md",
)
EXPECTED_DIRS: tuple[str, ...] = ("artifacts",)

# Local tooling/cache directories that are never part of the project tree.
IGNORED_DIRS = frozenset({".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
# artifacts/ holds generated deliverables, so its contents are not enumerated.
GENERATED_DIRS = ("artifacts",)

SECRET_PATTERNS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(r"\bATATT[A-Za-z0-9_=\-]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
)
FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
# Files that may legitimately be empty (runtime data created by `orchestrator.py init`).
MAY_BE_EMPTY = frozenset({"todo/__init__.py", "requirements.txt", "sdlc/state.json", "sdlc/audit.log.jsonl"})


def frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER.match(text)
    if not match:
        return {}
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if line and not line[0].isspace() and ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip("'\"")
    return meta


def check_structure(root: Path) -> list[str]:
    problems: list[str] = []
    for rel in EXPECTED_FILES:
        path = root / rel
        if not path.is_file():
            problems.append(f"missing file: {rel}")
    for rel in EXPECTED_DIRS:
        if not (root / rel).is_dir():
            problems.append(f"missing directory: {rel}/")

    expected = set(EXPECTED_FILES)
    for path in sorted(root.rglob("*")):
        rel_path = path.relative_to(root)
        parts = rel_path.parts
        if any(p in IGNORED_DIRS for p in parts) or path.suffix in {".pyc", ".tmp"} or path.name == ".DS_Store":
            continue
        if rel_path.as_posix() == "sdlc/.lock":  # runtime lock created by orchestrator.py, git-ignored
            continue
        if parts[0] in GENERATED_DIRS:
            continue
        if path.is_file() and rel_path.as_posix() not in expected:
            problems.append(f"unexpected file (not in the mandated structure): {rel_path.as_posix()}")
    return problems


def check_content(root: Path) -> list[str]:
    problems: list[str] = []

    for rel in EXPECTED_FILES:
        path = root / rel
        if path.is_file() and path.stat().st_size == 0 and rel not in MAY_BE_EMPTY:
            problems.append(f"empty file: {rel}")

    for agent in AGENTS:
        rel = f".github/agents/{agent}.agent.md"
        path = root / rel
        if path.is_file():
            meta = frontmatter(path.read_text(encoding="utf-8"))
            if not meta.get("description"):
                problems.append(f"{rel}: frontmatter 'description' missing")
            if not meta.get("name"):
                problems.append(f"{rel}: frontmatter 'name' missing")
    for agent in AGENTS:
        rel = f".github/prompts/{agent}.prompt.md"
        path = root / rel
        if path.is_file():
            meta = frontmatter(path.read_text(encoding="utf-8"))
            if not meta.get("description"):
                problems.append(f"{rel}: frontmatter 'description' missing")
            if not meta.get("agent"):
                problems.append(f"{rel}: frontmatter 'agent' missing")
    for skill in SKILLS:
        rel = f".github/skills/{skill}/SKILL.md"
        path = root / rel
        if path.is_file():
            meta = frontmatter(path.read_text(encoding="utf-8"))
            if meta.get("name") != skill:
                problems.append(f"{rel}: frontmatter 'name' must equal the folder name '{skill}'")
            if not meta.get("description"):
                problems.append(f"{rel}: frontmatter 'description' missing")

    problems += _check_json_wiring(root)

    for rel in EXPECTED_FILES:
        path = root / rel
        if path.is_file() and rel != "tools/audit_repo.py":
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if any(p.search(text) for p in SECRET_PATTERNS):
                problems.append(f"{rel}: possible hardcoded credential")
    return problems


def _check_json_wiring(root: Path) -> list[str]:
    problems: list[str] = []

    mcp = root / ".vscode/mcp.json"
    if mcp.is_file() and mcp.stat().st_size:
        try:
            data = json.loads(mcp.read_text(encoding="utf-8"))
            servers = data.get("servers", {})
            for name in ("atlassian", "github"):
                if name not in servers:
                    problems.append(f".vscode/mcp.json: server '{name}' not configured")
            text = json.dumps(data)
            for literal in re.findall(r'"(?:Authorization|token|apiKey|api_key|password)"\s*:\s*"([^"]*)"', text, re.I):
                if not re.search(r"\$\{(input|env):", literal):
                    problems.append(".vscode/mcp.json: credential-like field is not an ${input:...}/${env:...} reference")
        except json.JSONDecodeError as exc:
            problems.append(f".vscode/mcp.json: invalid JSON ({exc})")

    hooks = root / ".github/hooks/hooks.json"
    if hooks.is_file() and hooks.stat().st_size:
        try:
            data = json.loads(hooks.read_text(encoding="utf-8"))
            entries = data.get("hooks", {}).get("preToolUse")
            if data.get("version") != 1 or not entries or "hooks/guard.py" not in json.dumps(entries):
                problems.append(".github/hooks/hooks.json: must be version 1 and run hooks/guard.py on preToolUse")
        except json.JSONDecodeError as exc:
            problems.append(f".github/hooks/hooks.json: invalid JSON ({exc})")

    phases = root / "sdlc/phases.json"
    if phases.is_file() and phases.stat().st_size:
        try:
            data = json.loads(phases.read_text(encoding="utf-8"))
            agents = [p.get("agent") for p in data.get("phases", [])]
            if agents != list(AGENTS):
                problems.append(f"sdlc/phases.json: phase agents must be {list(AGENTS)}, found {agents}")
        except json.JSONDecodeError as exc:
            problems.append(f"sdlc/phases.json: invalid JSON ({exc})")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--structure", action="store_true", help="check the file tree only")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    problems = check_structure(args.root)
    if not args.structure:
        problems += check_content(args.root)

    if problems:
        print(f"audit FAILED: {len(problems)} finding(s)", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("audit passed: structure only" if args.structure else "audit passed: structure and content")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
