#!/usr/bin/env python3
"""Copilot hook: security guard and MCP evidence recorder.

  python3 hooks/guard.py pre    # preToolUse : print {} (no objection) or a deny decision
  python3 hooks/guard.py post   # postToolUse: record Atlassian/GitHub MCP results as audit evidence

Reads one JSON event on stdin. Fails closed on `pre`: malformed input or any internal error
yields a deny decision. Guardrail for cooperative agents, not a sandbox; see docs/CONTRACT.md.
Reuses orchestrator.py (no duplicated logic). Standard library only.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import orchestrator as orc  # noqa: E402

SHELL_TOOLS = frozenset({"bash", "sh", "zsh", "powershell", "pwsh", "shell", "terminal", "execute", "run_command",
                         "run_in_terminal", "runinterminal", "send_to_terminal"})
WRITE_HINTS = ("edit", "write", "create", "replace", "patch", "delete", "remove", "move", "rename", "insert",
               "append", "save", "mkdir", "str_replace")
PATH_KEYS = frozenset({"path", "filepath", "file_path", "filename", "file", "uri", "dirpath", "dir_path", "old_path",
                       "new_path", "oldpath", "newpath", "target", "destination", "paths", "files", "directory"})
CONTENT_KEYS = frozenset({"content", "newstring", "new_str", "new_string", "newcode", "new_text", "text", "file_text",
                          "insert_text", "patch", "input"})
READONLY_PROGRAMS = frozenset({"cat", "head", "tail", "less", "more", "grep", "egrep", "rg", "wc", "ls", "stat", "diff",
                               "jq", "file", "shasum", "sha256sum", "echo", "pwd", "which", "find"})
GIT_READONLY = frozenset({"diff", "log", "show", "status", "blame", "ls-files", "branch", "rev-parse", "remote"})
WRITER_PROGRAMS = frozenset({"mv", "cp", "rm", "tee", "truncate", "touch", "install", "ln", "mkdir", "rmdir"})
INTERPRETERS = frozenset({"python", "python3", "node", "ruby", "perl", "php", "deno", "bun"})
LOCAL_TOOL_GROUPS = frozenset({"edit", "vscode", "execute", "read", "search", "terminal", "runcommands", "runtasks", "agent",
                               "todo", "web", "browser", "notebook"})

GITHUB_DENY = re.compile(r"(?i)merge_pull_request|delete_(file|repository|branch)|create_repository|fork_repository|force")
GITHUB_GATED_WRITE = re.compile(r"(?i)create_branch|push_files|create_or_update_file")
GITHUB_TOOL = re.compile(r"(?i)github")
GITHUB_WRITE = re.compile(r"(?i)(?:^|[_/.])(?:create|update|add|delete|push|merge|fork|close|reopen|assign|request|dismiss|submit|edit|remove|"
                          r"lock|unlock|transfer|set|enable|disable|run|rerun|cancel|dispatch)|_write\b")
ATLASSIAN_WRITE = re.compile(r"(?:^|[_/.])(?:create|update|edit|delete|add|remove|transition|assign|move|link|archive)")
ATLASSIAN_TOOL = re.compile(r"(?i)atlassian|confluence|jira")

_HUMAN_ONLY = re.compile(r"orchestrator\.py\S*\s+(?:(?:--root\s+\S+|--json|-v|--verbose)\s+)*(?:"
                         + "|".join(re.escape(c) for c in orc.HUMAN_ONLY_COMMANDS) + r")\b")
_PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\s*$", re.MULTILINE)
_SEGMENTS = re.compile(r"\|\||&&|;|\||\n")
_REDIRECT = re.compile(r">>?\s*([^\s;&|<>]+)")
_ENV_FILE = re.compile(r"(^|/)\.env(\.(?!example$)[^/]*)?$", re.IGNORECASE)
_SECRET_FILE = re.compile(r"(?i)(\.pem|\.key|\.p12|\.pfx|(^|/)id_(rsa|dsa|ecdsa|ed25519)(\.pub)?)$")
_URL = re.compile(r"https://[^\s\"'<>\\)\]]+")


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str = ""
    tool: str = ""
    target: str = ""

    def output(self) -> dict[str, str]:
        if self.allow:
            return {}
        return {"permissionDecision": "deny", "permissionDecisionReason": f"SDLC guard: {self.reason}"}


ALLOW = Decision(True)


def deny(reason: str, tool: str = "", target: str = "") -> Decision:
    return Decision(False, reason, tool, target)


# --------------------------------------------------------------------------- event parsing
def parse_event(event: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Accept camelCase (toolName/toolArgs) and snake_case (tool_name/tool_input) payloads."""
    name = event.get("toolName", event.get("tool_name"))
    if not isinstance(name, str) or not name:
        raise ValueError("event has no tool name")
    args: Any = event.get("toolArgs", event.get("tool_input", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {"input": args}
    if not isinstance(args, dict):
        args = {"input": args} if args is not None else {}
    return name, args


def walk(node: Any, key: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, str(k).lower())
    elif isinstance(node, list):
        for item in node:
            yield from walk(item, key)
    else:
        yield key, node


def extract_paths(args: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for key, value in walk(args):
        if not isinstance(value, str) or not value.strip():
            continue
        if key in PATH_KEYS:
            found.append(unquote(urlparse(value).path) if value.startswith("file://") else value.strip())
        if key in CONTENT_KEYS or key == "command":
            found.extend(m.group(1) for m in _PATCH_FILE.finditer(value))
    return list(dict.fromkeys(found))


def extract_content(args: dict[str, Any]) -> str:
    return "\n".join(v for k, v in walk(args) if k in CONTENT_KEYS and isinstance(v, str))


# def _blocks_text(node: Any) -> str:
#     """Flatten a tool result (string, dict, or list of content blocks) into text."""
#     if node is None:
#         return ""
#     if isinstance(node, str):
#         return node
#     if isinstance(node, list):
#         return "\n".join(part for part in (_blocks_text(item) for item in node) if part)
#     if isinstance(node, dict):
#         for key in ("textResultForLlm", "text_result_for_llm", "text", "content", "output", "result"):
#             if key in node:
#                 text = _blocks_text(node[key])
#                 if text:
#                     return text
#         return json.dumps(node, ensure_ascii=False)  # unknown shape: keep it so URLs and length are still seen
#     return str(node)




def _blocks_text(node: Any) -> str:
    """Flatten an MCP tool result into its text content."""
    if node is None:
        return ""

    if isinstance(node, str):
        return node

    if isinstance(node, list):
        return "\n".join(
            part for part in (_blocks_text(item) for item in node) if part
        )

    if isinstance(node, dict):
        # Prefer known text fields, avoiding JSON wrapper text in result_chars.
        for key in (
            "textResultForLlm",
            "text_result_for_llm",
            "text",
            "content",
            "output",
            "result",
        ):
            if key in node:
                text = _blocks_text(node[key])
                if text:
                    return text

        # Preserve readable text from MCP content blocks.
        return json.dumps(node, ensure_ascii=False)

    return str(node)



def result_text(event: dict[str, Any]) -> tuple[str, bool]:
    """Return (result text, is_error) from either `toolResult` or `tool_response` style payloads."""
    result: Any = None
    for key in ("toolResult", "tool_result", "toolResponse", "tool_response"):
        if event.get(key) is not None:
            result = event[key]
            break
    if result is None:
        return "", False
    is_error = False
    if isinstance(result, dict):
        kind = result.get("resultType", result.get("result_type"))
        is_error = (kind is not None and str(kind) != "success") or bool(result.get("isError", result.get("is_error")))
    return _blocks_text(result), is_error


# --------------------------------------------------------------------------- policy
class Guard:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.orch = orc.Orchestrator(self.root)  # no confirm callback: the guard can never approve anything
        self.protected = tuple(dict.fromkeys(self.orch.workflow.protected_paths))

    def active_phase(self) -> orc.Phase | None:
        return self.orch.active_phase()

    # ---- entry
    def evaluate(self, event: dict[str, Any]) -> Decision:
        try:
            tool, args = parse_event(event)
        except ValueError as exc:
            return deny(f"malformed hook event ({exc})")
        low = tool.lower()

        kind = orc.classify_tool(tool, self.orch.workflow)
        if kind == "github_pr_created":
            return self._check_pr_creation(tool, args)
        if GITHUB_DENY.search(tool):
            return deny("merging, deleting, forking, or creating repositories is reserved for humans", tool)
        if GITHUB_GATED_WRITE.search(tool):
            return self._check_github_write(tool, args)
        if GITHUB_TOOL.search(tool) and GITHUB_WRITE.search(tool):
            return deny("GitHub write operations other than the authorized pull request are human-only", tool)
        if ATLASSIAN_TOOL.search(tool):
            if ATLASSIAN_WRITE.search(tool):
                return deny("Atlassian MCP is read-only for agents; creating or changing Jira/Confluence content is not permitted", tool)
            return ALLOW

        prefix = low.split("/", 1)[0] if "/" in low else ""
        if (prefix and prefix not in LOCAL_TOOL_GROUPS) or low.startswith("mcp_"):
            # remote MCP tool: its path-like arguments are not local files
            found = orc.find_secrets(extract_content(args))
            if found:
                return deny(f"content appears to contain a secret ({', '.join(found)}); never send credentials", tool)
            return ALLOW

        shell = low in SHELL_TOOLS or ("command" in args and not any(h in low for h in WRITE_HINTS))
        secrets = [] if shell else orc.find_secrets(extract_content(args))
        if secrets:
            return deny(f"content appears to contain a secret ({', '.join(secrets)}); never write credentials", tool)
        if shell:
            return self._check_shell(tool, str(args.get("command", args.get("input", ""))))

        paths = extract_paths(args)
        if any(h in low for h in WRITE_HINTS):
            if not paths:
                return deny("write tool without a determinable target path", tool)
            for path in paths:
                decision = self.check_write(path, tool)
                if not decision.allow:
                    return decision
            return ALLOW
        for path in paths:
            rel = orc.to_repo_relative(self.root, path)
            if rel and (_ENV_FILE.search(rel) or _SECRET_FILE.search(rel)):
                return deny("reading credential files is not permitted", tool, rel)
        return ALLOW

    # ---- GitHub MCP
    def _check_pr_creation(self, tool: str, args: dict[str, Any]) -> Decision:
        ok, reason = self.orch.pr_creation_check(args)
        return ALLOW if ok else deny(reason, tool)

    def _check_github_write(self, tool: str, args: dict[str, Any]) -> Decision:
        state, _ = self.orch.state.load()
        auth = state["phases"]["pr"].get("pr_authorization")
        if self.orch._status(state, "pr") != orc.Status.IN_PROGRESS.value or not auth:
            return deny("GitHub write operations require the 'pr' phase in progress and a human 'authorize-pr'", tool)
        if f"{args.get('owner', '')}/{args.get('repo', '')}" != auth["repo"]:
            return deny("repository differs from the authorized one", tool)
        if str(args.get("branch", "")) != auth["head"]:
            return deny(f"writes are allowed only on the authorized head branch '{auth['head']}'", tool)
        return ALLOW

    # ---- file writes
    def is_protected(self, rel: str) -> bool:
        low = rel.lower()
        return any(orc.glob_match(p.lower(), low) for p in self.protected)

    def check_write(self, raw_path: str, tool: str = "") -> Decision:
        rel = orc.to_repo_relative(self.root, raw_path)
        if rel is None:
            return deny("writes outside the repository are not permitted", tool, raw_path)
        if self.is_protected(rel):
            return deny("protected governance/state file; only the orchestrator or a human may change it", tool, rel)
        if _ENV_FILE.search(rel) or _SECRET_FILE.search(rel):
            return deny("credential files must not be written", tool, rel)
        try:
            phase = self.active_phase()
        except orc.OrchestratorError as exc:
            return deny(f"workflow state is not trustworthy ({exc}); writes are blocked until it is restored", tool, rel)
        owner = self.orch.workflow.owner_of(rel)
        if rel == "artifacts" or rel.startswith("artifacts/"):
            if owner is None:
                return deny("artifact path is not an output of any phase (archive is orchestrator-managed)", tool, rel)
            if phase is None or owner.id != phase.id:
                return deny(f"artifact belongs to phase '{owner.id}', but the active phase is "
                            f"'{phase.id if phase else 'none'}'", tool, rel)
            return ALLOW
        if phase is None:
            return deny("no phase is in progress; run 'orchestrator.py start <phase>' first", tool, rel)
        if any(orc.glob_match(g, rel) for g in phase.write_globs):
            return ALLOW
        return deny(f"path is outside the writable paths of active phase '{phase.id}'", tool, rel)

    # ---- shell (best effort)
    def _protected_fragments(self) -> list[str]:
        frags = []
        for pattern in self.protected:
            if pattern == "orchestrator.py":
                continue  # running the CLI is fine; human-only subcommands are denied separately
            base = pattern[:-2] if pattern.endswith("/**") else pattern
            if "*" not in base:
                frags.append(base.lower())
        return frags

    def _check_shell(self, tool: str, command: str) -> Decision:
        if not command.strip():
            return ALLOW
        flat = " ".join(command.split())
        if orc.find_secrets(command):
            return deny("command contains what looks like a credential", tool)
        if _HUMAN_ONLY.search(flat):
            return deny("approve/reopen/init/authorize-pr are human-only orchestrator commands", tool)
        if re.search(r"\b(import|from)\s+orchestrator\b|orchestrator\s*\.\s*(Orchestrator|StateManager|AuditLog)", flat):
            return deny("do not drive the orchestrator through inline code; use the CLI", tool)
        if re.search(r"\b(curl|wget)\b[^|;]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", flat):
            return deny("piping downloaded content into a shell is not permitted", tool)
        if re.search(r"\b(mkfs(\.\w+)?|shutdown|reboot|halt)\b|:\(\)\s*\{|\bchmod\s+(-R\s+)?0?777\b", flat):
            return deny("destructive system command", tool)
        for target in _REDIRECT.findall(command):
            target = target.strip("'\"")
            if target and not target.startswith("&") and target != "/dev/null":
                decision = self.check_write(target, tool)
                if not decision.allow:
                    return decision
        lowered = command.lower()
        mentions_protected = any(f in lowered for f in self._protected_fragments())
        for segment in _SEGMENTS.split(command):
            decision = self._check_segment(segment, tool, mentions_protected)
            if not decision.allow:
                return decision
        return ALLOW

    def _check_segment(self, segment: str, tool: str, mentions_protected: bool) -> Decision:
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError:
            tokens = segment.split()
        while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
            tokens.pop(0)
        if not tokens:
            return ALLOW
        prog, args = Path(tokens[0]).name.lower(), tokens[1:]
        if prog in {"sudo", "su", "doas"}:
            return deny("privilege escalation is not permitted", tool)
        for tok in tokens:
            if _ENV_FILE.search(tok) or _SECRET_FILE.search(tok):
                return deny("access to credential files is not permitted", tool, tok)
        if prog == "rm":
            flags = "".join(a.lstrip("-") for a in args if a.startswith("-")).lower()
            targets = [a for a in args if not a.startswith("-")]
            if "r" in flags and "f" in flags and any(t in {"/", "~", "$HOME", ".", "..", "*", "/*", "./", ".git", ".git/"} for t in targets):
                return deny("recursive forced delete of a broad path", tool)
        if prog == "git":
            decision = self._check_git(args, tool)
            if not decision.allow:
                return decision
            sub = next((a for a in args if not a.startswith("-")), "")
            if mentions_protected and sub not in GIT_READONLY:
                return deny("git commands touching governance/state files must be read-only", tool)
            return ALLOW
        if prog == "gh":
            if re.search(r"\bpr\s+(merge|create)\b|\brepo\s+delete\b|\brelease\s+delete\b|\bauth\s+token\b|\bsecret\b", " ".join(args)):
                return deny("pull requests are created through GitHub MCP after authorization; merging/deleting is human-only", tool)
        if prog in WRITER_PROGRAMS or (prog == "sed" and any(a.startswith("-i") or a == "--in-place" for a in args)):
            for tok in args:
                if tok.startswith("-") or ("/" not in tok and "." not in tok):
                    continue
                decision = self.check_write(tok, tool)
                if not decision.allow:
                    return decision
        if prog in INTERPRETERS and mentions_protected and any(a in {"-c", "-e", "-"} for a in args):
            return deny("inline interpreter code touching governance/state files is not permitted", tool)
        if mentions_protected and prog not in READONLY_PROGRAMS and prog not in INTERPRETERS:
            return deny("commands touching state, audit, hook, or governance files must be read-only", tool)
        return ALLOW

    @staticmethod
    def _check_git(args: list[str], tool: str) -> Decision:
        sub = next((a for a in args if not a.startswith("-")), "")
        rest = " ".join(args)
        if sub == "push":
            if re.search(r"(^|\s)(--force|-f|--force-with-lease|--mirror|--delete)\b", rest) or re.search(r"\s\+\S", rest):
                return deny("force or destructive push is not permitted", tool)
            positional = [a for a in args if not a.startswith("-")][1:]  # drop 'push'; then remote and refspecs
            for ref in positional:
                dst = ref.lstrip("+").split(":")[-1].removeprefix("refs/heads/")
                if dst in {"main", "master"}:
                    return deny("pushing to main/master is not permitted; use a branch and a pull request", tool)
        if sub == "reset" and "--hard" in args:
            return deny("git reset --hard can destroy work", tool)
        if sub == "clean" and re.search(r"-\w*f", rest):
            return deny("git clean -f can destroy work", tool)
        if sub in {"commit", "push", "rebase"} and re.search(r"(^|\s)(--no-verify|-n)\b", rest):
            return deny("bypassing git hooks is not permitted", tool)
        if sub == "config" and re.search(r"--(global|system)\b", rest):
            return deny("modifying global git configuration is not permitted", tool)
        if sub in {"filter-branch", "filter-repo"}:
            return deny("history rewriting is not permitted", tool)
        return ALLOW


# --------------------------------------------------------------------------- evidence recording
# def record_mcp_result(event: dict[str, Any], root: Path) -> dict[str, Any] | None:
#     """Append an `mcp.call` audit entry for Atlassian/GitHub-PR results. Stores metadata, never content."""
#     tool, args = parse_event(event)
#     orch = orc.Orchestrator(root)
#     if not orch.workflow.mcp_enabled:  # integrations switched off: no MCP evidence is collected
#         return None
#     kind = orc.classify_tool(tool, orch.workflow)
#     if kind is None or orch.audit.last_anchor() is None:  # nothing to attach evidence to before 'init'
#         return None
#     text, is_error = result_text(event)
#     urls = sorted({u.rstrip(".,;)") for u in _URL.findall(text)})[:50]
#     details: dict[str, Any] = {"tool": tool, "kind": kind, "is_error": is_error, "result_chars": len(text), "urls": urls}
#     if kind == "github_pr_created":
#         details["target"] = f"{args.get('owner', '')}/{args.get('repo', '')} {args.get('head', '')} {args.get('base', '')}"
#         try:
#             details["pr_body_digest"] = orc.pr_body_digest(orch.checker.read_output(orch.workflow.phase("pr")))
#         except (OSError, UnicodeDecodeError):
#             details["pr_body_digest"] = None
#     return orch.audit.append("mcp.call", actor="guard", details=details)




def record_mcp_result(event: dict[str, Any], root: Path) -> dict[str, Any] | None:
    """Append an `mcp.call` audit entry for Atlassian/GitHub-PR results. Stores metadata, never content."""
    tool, args = parse_event(event)
    orch = orc.Orchestrator(root)

    if not orch.workflow.mcp_enabled:
        return None

    kind = orc.classify_tool(tool, orch.workflow)
    if kind is None or orch.audit.last_anchor() is None:
        return None

    text, is_error = result_text(event)

    raw_result = next(
        (
            event[key]
            for key in ("toolResult", "tool_result", "toolResponse", "tool_response")
            if event.get(key) is not None
        ),
        None,
    )

    searchable_result = text
    if isinstance(raw_result, (dict, list)):
        searchable_result += "\n" + json.dumps(
            raw_result, ensure_ascii=False
        )

    urls = sorted({
        u.rstrip(".,;)")
        for u in _URL.findall(searchable_result)
    })[:50]

    details: dict[str, Any] = {
        "tool": tool,
        "kind": kind,
        "is_error": is_error,
        "result_chars": len(text),
        "urls": urls,
    }

    if kind == "github_pr_created":
        details["target"] = (
            f"{args.get('owner', '')}/{args.get('repo', '')} "
            f"{args.get('head', '')} {args.get('base', '')}"
        )
        try:
            details["pr_body_digest"] = orc.pr_body_digest(
                orch.checker.read_output(orch.workflow.phase("pr"))
            )
        except (OSError, UnicodeDecodeError):
            details["pr_body_digest"] = None

    return orch.audit.append(
        "mcp.call", actor="guard", details=details
    )


def record_denial(root: Path, decision: Decision) -> None:
    """Best-effort audit of a denial; never includes tool arguments or content."""
    try:
        orch = orc.Orchestrator(root)
        # Before 'init' there is no state anchor; writing now would make 'init' refuse to run.
        if not orch.audit.verify() and orch.audit.last_anchor() is not None:
            orch.audit.append("guard.denied", actor="guard",
                              details={"tool": decision.tool, "target": decision.target, "reason": decision.reason})
    except Exception:  # noqa: BLE001
        pass


def main(argv: list[str] | None = None) -> int:
    mode = (argv if argv is not None else sys.argv[1:] or ["pre"])[0]

    def emit_deny(reason: str) -> int:
        print(json.dumps({"permissionDecision": "deny", "permissionDecisionReason": f"SDLC guard: {reason}"}))
        return 0

    try:
        event = json.loads(sys.stdin.read())
        if not isinstance(event, dict):
            raise ValueError("event is not an object")
    except (ValueError, UnicodeDecodeError, OSError):
        if mode == "pre":
            return emit_deny("could not parse hook event; failing closed")
        print("{}")
        return 0

    if mode == "post":
        try:
            record_mcp_result(event, ROOT)
        except Exception as exc:  # noqa: BLE001 - a recording failure only withholds evidence
            print(f"guard: could not record evidence: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("{}")
        return 0

    try:
        decision = Guard(ROOT).evaluate(event)
    except Exception as exc:  # noqa: BLE001 - fail closed
        print(f"guard internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return emit_deny("internal guard error; failing closed")
    if not decision.allow:
        record_denial(ROOT, decision)
    print(json.dumps(decision.output()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
