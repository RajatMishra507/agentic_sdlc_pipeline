#!/usr/bin/env python3
"""Agentic SDLC orchestrator: CLI and workflow engine.

Coordinates eight phase agents (see sdlc/phases.json) and enforces phase order,
artifact ownership, validation, human approvals, content-hash integrity, and an
append-only hash-chained audit log. Standard library only.

Evidence model (no faked integrations): the guard hook (hooks/guard.py) records every
Atlassian/GitHub MCP call and the Verification test run is executed by this CLI. Phase
submission re-verifies those audit entries; a document that merely *claims* a Confluence
fetch, a test pass, or a created pull request is rejected.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import getpass
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

try:  # POSIX advisory locking; absent on Windows.
    import fcntl  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

__version__ = "0.1.0"
ROOT = Path(__file__).resolve().parent
log = logging.getLogger("sdlc")

GENESIS_HASH = "0" * 64
STATE_SCHEMA_VERSION = 1
PHASE_IDS = ("requirements", "architecture", "design-review", "planning", "implementation", "review", "verify", "pr")
EVIDENCE_KINDS = ("confluence", "checks", "github_pr")
MIN_EVIDENCE_CHARS = 100  # an MCP result shorter than this cannot be "actual user stories"
PR_RECORD_HEADING = "## Pull Request Record"
ARCHIVE_DIRNAME = "_archive"
HUMAN_ONLY_COMMANDS = ("approve", "reopen", "init", "authorize-pr")


# ======================================================================================
# Exit codes and errors
# ======================================================================================
class ExitCode(IntEnum):
    OK = 0
    VALIDATION_FAILED = 1
    USAGE = 2
    CONFIG_ERROR = 3
    STATE_ERROR = 4
    TRANSITION_DENIED = 5
    APPROVAL_DENIED = 6
    IO_ERROR = 7


class OrchestratorError(Exception):
    exit_code: ExitCode = ExitCode.IO_ERROR


class ConfigError(OrchestratorError):
    exit_code = ExitCode.CONFIG_ERROR


class StateError(OrchestratorError):
    exit_code = ExitCode.STATE_ERROR


class TransitionError(OrchestratorError):
    exit_code = ExitCode.TRANSITION_DENIED


class ApprovalError(OrchestratorError):
    exit_code = ExitCode.APPROVAL_DENIED


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    path: str | None = None
    phase: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {"code": self.code, "message": self.message, "path": self.path, "phase": self.phase}

    def __str__(self) -> str:
        who = f"({self.phase}) " if self.phase else ""
        where = f" [{self.path}]" if self.path else ""
        return f"{self.code}: {who}{self.message}{where}"


class ValidationFailed(OrchestratorError):
    exit_code = ExitCode.VALIDATION_FAILED

    def __init__(self, message: str, issues: list[Issue] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []


# ======================================================================================
# Filesystem and hashing helpers
# ======================================================================================
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # pragma: no cover
        return os.environ.get("USER", "unknown")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(data: Any) -> str:
    return sha256_bytes(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())


def atomic_write_text(path: Path, text: str) -> None:
    """Temp file + fsync + rename: readers never observe a partially written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


_lock_depth: dict[str, int] = {}
_lock_handles: dict[str, Any] = {}
_thread_lock = threading.RLock()


@contextlib.contextmanager
def file_lock(lock_path: Path) -> Iterator[None]:
    """Re-entrant exclusive lock shared by the CLI and the guard hook."""
    key = str(lock_path)
    with _thread_lock:
        depth = _lock_depth.get(key, 0)
        if depth == 0:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(lock_path, "a+")
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            _lock_handles[key] = handle
        _lock_depth[key] = depth + 1
        try:
            yield
        finally:
            _lock_depth[key] -= 1
            if _lock_depth[key] == 0:
                handle = _lock_handles.pop(key)
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                handle.close()
                del _lock_depth[key]


def safe_relative(path_text: str) -> str:
    """Normalize a repo-relative POSIX path; reject absolute paths and traversal."""
    if not path_text or "\x00" in path_text:
        raise ValueError("empty or invalid path")
    normalized = path_text.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError(f"absolute path not allowed: {path_text}")
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise ValueError(f"path traversal not allowed: {path_text}")
    return "/".join(parts)


def to_repo_relative(root: Path, candidate: str) -> str | None:
    """Repo-relative POSIX path for a path or file:// URI (symlinks resolved); None if outside."""
    root_real = Path(os.path.realpath(root))
    raw = Path(candidate)
    full = raw if raw.is_absolute() else root_real / raw
    resolved = Path(os.path.realpath(full))
    try:
        return resolved.relative_to(root_real).as_posix()
    except ValueError:
        return None


def glob_match(pattern: str, rel_path: str) -> bool:
    """Glob with `*` (within a segment), `?`, and `**` (across segments)."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.fullmatch("".join(out), rel_path) is not None


_SKIP_DIRS = frozenset({".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", ".mypy_cache"})


def source_digest(root: Path, globs: Sequence[str]) -> str:
    """Deterministic digest of every source file matched by `globs` (names and contents)."""
    entries: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for name in sorted(filenames):
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            if name.endswith((".pyc", ".tmp")):
                continue
            if any(glob_match(g, rel) for g in globs) and full.is_file() and not full.is_symlink():
                entries.append(f"{rel}\0{sha256_file(full)}")
    return sha256_bytes("\n".join(sorted(entries)).encode())


# ======================================================================================
# Secret and placeholder detection (shared with the guard hook)
# ======================================================================================
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("github-fine-grained-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("atlassian-api-token", re.compile(r"\bATATT[A-Za-z0-9_=\-]{20,}")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY")),
    (
        "generic-credential",
        re.compile(r"(?i)\b(?:api[_-]?key|secret|token|passw(?:or)?d)\b\s*[:=]\s*['\"][^'\"\s$]{12,}['\"]"),
    ),
)
PLACEHOLDER_RE = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b|<placeholder>|\{\{[^}\n]*\}\}|(?i:lorem ipsum)")


def find_secrets(text: str) -> list[str]:
    """Names of matching secret patterns (never the matched values)."""
    return [name for name, pattern in SECRET_PATTERNS if pattern.search(text)]


def find_placeholders(text: str) -> list[str]:
    return sorted({m.group(0) for m in PLACEHOLDER_RE.finditer(text)})


# ======================================================================================
# Configuration: sdlc/phases.json
# ======================================================================================
@dataclass(frozen=True)
class OutputSpec:
    path: str
    description: str
    min_bytes: int
    max_bytes: int
    required_sections: tuple[str, ...]
    required_patterns: tuple[str, ...]
    mcp_sections: tuple[str, ...] = ()  # enforced only when integrations.mcp_evidence is true
    mcp_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class Phase:
    id: str
    order: int
    name: str
    agent: str
    purpose: str
    prerequisites: tuple[str, ...]
    consumes: tuple[str, ...]
    external_inputs: tuple[str, ...]
    outputs: tuple[OutputSpec, ...]
    validation_rules: tuple[str, ...]
    completion_conditions: tuple[str, ...]
    approval_required: bool
    write_globs: tuple[str, ...]
    evidence: str | None

    @property
    def output_paths(self) -> tuple[str, ...]:
        return tuple(o.path for o in self.outputs)


@dataclass(frozen=True)
class Workflow:
    phases: tuple[Phase, ...]
    source_globs: tuple[str, ...]
    protected_paths: tuple[str, ...]
    evidence_tools: dict[str, tuple[str, ...]]
    mcp_enabled: bool = False

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(p.id for p in self.phases)

    def phase(self, phase_id: str) -> Phase:
        for p in self.phases:
            if p.id == phase_id:
                return p
        raise ConfigError(f"unknown phase '{phase_id}'; valid phases: {', '.join(self.ids)}")

    def downstream(self, phase_id: str) -> tuple[Phase, ...]:
        order = self.phase(phase_id).order
        return tuple(p for p in self.phases if p.order > order)

    def owner_of(self, rel_path: str) -> Phase | None:
        for p in self.phases:
            if rel_path in p.output_paths:
                return p
        return None


def _req(cond: bool, where: str, message: str) -> None:
    if not cond:
        raise ConfigError(f"{where}: {message}")


def _str(obj: dict[str, Any], key: str, where: str) -> str:
    value = obj.get(key)
    _req(isinstance(value, str) and bool(value.strip()), where, f"'{key}' must be a non-empty string")
    return value


def _strs(obj: dict[str, Any], key: str, where: str, *, required: bool = True) -> tuple[str, ...]:
    if key not in obj and not required:
        return ()
    value = obj.get(key)
    _req(isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value), where,
         f"'{key}' must be a list of non-empty strings")
    return tuple(value)


def _check_regexes(patterns: Sequence[str], where: str) -> None:
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError(f"{where}: invalid regex '{pattern}': {exc}") from exc


def parse_workflow(data: Any) -> Workflow:
    """Validate phases.json content; raises ConfigError on any violation."""
    _req(isinstance(data, dict), "phases.json", "top level must be an object")
    _req(data.get("schema_version") == 1, "phases.json", "'schema_version' must be 1")
    source_globs = _strs(data, "source_globs", "phases.json")
    protected = _strs(data, "protected_paths", "phases.json")
    integrations = data.get("integrations", {})
    _req(isinstance(integrations, dict) and isinstance(integrations.get("mcp_evidence", False), bool), "phases.json",
         "'integrations.mcp_evidence' must be a boolean")
    mcp_enabled = bool(integrations.get("mcp_evidence", False))
    raw_tools = data.get("evidence_tools")
    _req(isinstance(raw_tools, dict), "phases.json", "'evidence_tools' must be an object")
    evidence_tools: dict[str, tuple[str, ...]] = {}
    for kind, patterns in raw_tools.items():
        _req(kind in ("confluence", "github_pr_created"), "phases.json", f"unknown evidence tool kind '{kind}'")
        patterns = _strs(raw_tools, kind, "phases.json evidence_tools")
        _check_regexes(patterns, f"evidence_tools.{kind}")
        evidence_tools[kind] = patterns
    _req(set(evidence_tools) == {"confluence", "github_pr_created"}, "phases.json",
         "'evidence_tools' must define 'confluence' and 'github_pr_created'")

    raw_phases = data.get("phases")
    _req(isinstance(raw_phases, list) and raw_phases, "phases.json", "'phases' must be a non-empty list")
    phases: list[Phase] = []
    seen_outputs: set[str] = set()
    seen_agents: set[str] = set()
    for index, raw in enumerate(raw_phases, start=1):
        _req(isinstance(raw, dict), f"phases[{index - 1}]", "phase must be an object")
        pid = _str(raw, "id", f"phases[{index - 1}]")
        where = f"phase '{pid}'"
        _req(raw.get("order") == index, where, f"'order' must be {index}")
        agent = _str(raw, "agent", where)
        _req(re.fullmatch(r"[a-z][a-z0-9-]*", agent) is not None and agent not in seen_agents, where,
             "'agent' must be a unique lowercase-hyphen identifier")
        seen_agents.add(agent)
        prereqs = _strs(raw, "prerequisites", where)
        expected = (phases[-1].id,) if phases else ()
        _req(prereqs == expected, where, f"'prerequisites' must be exactly {list(expected)} (strict phase order)")
        raw_outputs = raw.get("outputs")
        _req(isinstance(raw_outputs, list) and raw_outputs, where, "'outputs' must be a non-empty list")
        outputs: list[OutputSpec] = []
        for out in raw_outputs:
            _req(isinstance(out, dict), where, "output must be an object")
            try:
                path = safe_relative(_str(out, "path", where))
            except ValueError as exc:
                raise ConfigError(f"{where}: {exc}") from exc
            _req(re.fullmatch(r"artifacts/[^/]+", path) is not None and not path.startswith("artifacts/_"), where,
                 f"output '{path}' must be a file directly inside artifacts/")
            _req(path not in seen_outputs, where, f"output '{path}' is owned by another phase")
            seen_outputs.add(path)
            min_b, max_b = out.get("min_bytes", 1), out.get("max_bytes", 1_000_000)
            _req(isinstance(min_b, int) and isinstance(max_b, int) and 0 <= min_b < max_b, where,
                 "'min_bytes'/'max_bytes' must be integers with min < max")
            patterns = _strs(out, "required_patterns", where, required=False)
            _check_regexes(patterns, where)
            mcp_patterns = _strs(out, "mcp_patterns", where, required=False)
            _check_regexes(mcp_patterns, where)
            outputs.append(OutputSpec(path, _str(out, "description", where), min_b, max_b,
                                      _strs(out, "required_sections", where, required=False), patterns,
                                      _strs(out, "mcp_sections", where, required=False), mcp_patterns))
        approval = raw.get("approval_required")
        _req(isinstance(approval, bool), where, "'approval_required' must be a boolean")
        _req(approval is True, where, "'approval_required' must be true: every phase requires explicit human approval")
        evidence = raw.get("evidence")
        _req(evidence is None or evidence in EVIDENCE_KINDS, where, f"'evidence' must be one of {EVIDENCE_KINDS}")
        write_globs = _strs(raw, "write_globs", where, required=False)
        _req(not any(g.startswith("artifacts") for g in write_globs), where, "'write_globs' must not target artifacts/")
        phases.append(Phase(
            id=pid, order=index, name=_str(raw, "name", where), agent=agent, purpose=_str(raw, "purpose", where),
            prerequisites=prereqs, consumes=_strs(raw, "consumes", where, required=False),
            external_inputs=_strs(raw, "external_inputs", where, required=False), outputs=tuple(outputs),
            validation_rules=_strs(raw, "validation_rules", where),
            completion_conditions=_strs(raw, "completion_conditions", where),
            approval_required=approval, write_globs=write_globs, evidence=evidence,
        ))
    _req(tuple(p.id for p in phases) == PHASE_IDS, "phases.json", f"phases must be, in order: {', '.join(PHASE_IDS)}")
    return Workflow(tuple(phases), source_globs, protected, evidence_tools, mcp_enabled)


def load_workflow(path: Path) -> Workflow:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"phase definitions not found: {path}") from None
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    try:
        return parse_workflow(json.loads(raw))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc


def classify_tool(tool_name: str, workflow: Workflow) -> str | None:
    """Map an MCP tool name to an evidence kind ('github_pr_created' wins over 'confluence')."""
    for kind in ("github_pr_created", "confluence"):
        if any(re.search(p, tool_name) for p in workflow.evidence_tools.get(kind, ())):
            return kind
    return None


def pr_body_digest(text: str) -> str:
    """Digest of pr.md up to (excluding) the Pull Request Record, which is filled in after creation."""
    head = re.split(r"(?m)^## Pull Request Record\s*$", text, maxsplit=1)[0]
    return sha256_bytes(head.strip().encode("utf-8"))


# ======================================================================================
# Audit log: append-only, hash-chained JSON Lines
# ======================================================================================
class AuditLog:
    """Each entry holds its own SHA-256 and the previous entry's hash, so edits and deletions of
    any non-final entry are detectable. Entries that change state also carry the state checksums."""

    def __init__(self, path: Path, lock_path: Path) -> None:
        self.path, self.lock_path = path, lock_path

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise StateError(f"cannot read audit log {self.path}: {exc}") from exc
        entries: list[dict[str, Any]] = []
        for number, line in enumerate(raw.splitlines(), start=1):
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise StateError(f"audit log line {number} is not valid JSON: {exc}") from exc
            if not isinstance(entry, dict):
                raise StateError(f"audit log line {number} is not a JSON object")
            entries.append(entry)
        return entries

    @staticmethod
    def entry_hash(entry: dict[str, Any]) -> str:
        return sha256_json({k: v for k, v in entry.items() if k != "hash"})

    def verify(self) -> list[str]:
        try:
            entries = self.read()
        except StateError as exc:
            return [str(exc)]
        problems: list[str] = []
        prev = GENESIS_HASH
        for index, entry in enumerate(entries, start=1):
            if entry.get("seq") != index:
                problems.append(f"entry {index}: expected seq {index}, found {entry.get('seq')!r}")
            if entry.get("prev_hash") != prev:
                problems.append(f"entry {index}: hash chain broken")
            if entry.get("hash") != self.entry_hash(entry):
                problems.append(f"entry {index}: content hash mismatch (entry modified)")
            prev = entry.get("hash", "")
        return problems

    def last_anchor(self) -> dict[str, Any] | None:
        for entry in reversed(self.read()):
            if entry.get("state_after"):
                return entry
        return None

    def append(self, event: str, *, phase: str | None = None, actor: str | None = None,
               details: dict[str, Any] | None = None, state_before: str | None = None,
               state_after: str | None = None) -> dict[str, Any]:
        with file_lock(self.lock_path):
            entries = self.read()
            if self.path.exists() and self.path.stat().st_size > 0:
                with self.path.open("rb") as handle:
                    handle.seek(-1, os.SEEK_END)
                    if handle.read(1) != b"\n":
                        raise StateError("audit log does not end with a newline (partial write?); refusing to append")
            entry: dict[str, Any] = {
                "seq": len(entries) + 1, "ts": utc_now(), "event": event, "actor": actor or current_user(),
                "phase": phase, "details": details or {}, "state_before": state_before,
                "state_after": state_after,
                "prev_hash": entries[-1].get("hash", GENESIS_HASH) if entries else GENESIS_HASH,
            }
            entry["hash"] = self.entry_hash(entry)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(entry, sort_keys=True, ensure_ascii=True) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise StateError(f"cannot append to audit log: {exc}") from exc
            return entry


# ======================================================================================
# State: checksum-protected and anchored to the audit log
# ======================================================================================
class Status(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    STALE = "stale"


def blank_phase_state() -> dict[str, Any]:
    return {"status": Status.NOT_STARTED.value, "started_at": None, "started_seq": None, "submitted_at": None,
            "artifact_hashes": {}, "approval": None, "stale_reason": None, "pr_authorization": None}


def checksum_of(state: dict[str, Any]) -> str:
    return sha256_json({k: v for k, v in state.items() if k != "checksum"})


def initial_state(workflow: Workflow) -> dict[str, Any]:
    now = utc_now()
    state: dict[str, Any] = {"schema_version": STATE_SCHEMA_VERSION, "revision": 0, "created_at": now,
                             "updated_at": now, "phases": {pid: blank_phase_state() for pid in workflow.ids}}
    state["checksum"] = checksum_of(state)
    return state


class StateManager:
    """Every mutation: lock -> verify state+audit -> audit entry (with before/after checksums) -> atomic write.

    A crash between the audit append and the state write leaves audit.state_before == state.checksum;
    that is detected as an interrupted transition and recovered. Any other mismatch is tampering."""

    def __init__(self, path: Path, audit: AuditLog, workflow: Workflow, lock_path: Path) -> None:
        self.path, self.audit, self.workflow, self.lock_path = path, audit, workflow, lock_path

    def read_raw(self) -> dict[str, Any]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise StateError(f"state file missing: {self.path}. Run 'orchestrator.py init' on a fresh repository, "
                             "or restore it with git.") from None
        except (OSError, UnicodeDecodeError) as exc:
            raise StateError(f"cannot read state file {self.path}: {exc}") from exc
        if not text.strip():
            raise StateError("sdlc/state.json is empty: run 'orchestrator.py init' (fresh repository) or restore it with git")
        try:
            state = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StateError(f"state file is corrupted (invalid JSON: {exc}); it was NOT modified. "
                             "Restore it with git or follow docs/RUNBOOK.md.") from exc
        self._check_shape(state)
        if state.get("checksum") != checksum_of(state):
            raise StateError("state checksum mismatch: sdlc/state.json was modified outside the orchestrator "
                             "(or partially written). Restore it with git or follow docs/RUNBOOK.md.")
        return state

    def _check_shape(self, state: Any) -> None:
        if not isinstance(state, dict) or state.get("schema_version") != STATE_SCHEMA_VERSION:
            raise StateError("state has an unsupported structure or schema_version")
        phases = state.get("phases")
        if not isinstance(phases, dict) or set(phases) != set(self.workflow.ids):
            raise StateError("state phases do not match sdlc/phases.json")
        valid = {s.value for s in Status}
        for pid, entry in phases.items():
            if not isinstance(entry, dict) or entry.get("status") not in valid \
                    or not isinstance(entry.get("artifact_hashes"), dict):
                raise StateError(f"state for phase '{pid}' is invalid")
        if not isinstance(state.get("revision"), int):
            raise StateError("state revision must be an integer")

    def load(self) -> tuple[dict[str, Any], bool]:
        """Return (state, interrupted)."""
        problems = self.audit.verify()
        if problems:
            raise StateError("audit log integrity failure: " + "; ".join(problems[:3]))
        state = self.read_raw()
        anchor = self.audit.last_anchor()
        if anchor is None:
            raise StateError("audit log has no state anchor; state cannot be trusted. Restore both files with git.")
        if anchor["state_after"] == state["checksum"]:
            return state, False
        if anchor.get("state_before") == state["checksum"]:
            return state, True
        raise StateError("state does not match the audit log (edited outside the orchestrator). "
                         "Restore both files with git or follow docs/RUNBOOK.md.")

    def initialize(self, actor: str | None = None) -> None:
        with file_lock(self.lock_path):
            if self.path.exists() and self.path.stat().st_size > 0 or \
                    self.audit.path.exists() and self.audit.path.stat().st_size > 0:
                raise StateError("already initialized: state or audit log is not empty")
            state = initial_state(self.workflow)
            self.audit.append("state.initialized", actor=actor, details={"phases": list(self.workflow.ids)},
                              state_after=state["checksum"])
            atomic_write_text(self.path, json.dumps(state, indent=2, sort_keys=True) + "\n")

    def apply(self, event: str, mutate: Callable[[dict[str, Any], int], dict[str, Any] | None], *,
              phase: str | None = None, actor: str | None = None) -> dict[str, Any]:
        """Atomically mutate state. `mutate(state, seq)` edits a deep copy; seq is the audit seq to be written."""
        with file_lock(self.lock_path):
            state, interrupted = self.load()
            if interrupted:
                self.audit.append("state.recovered", actor=actor, state_before=state["checksum"],
                                  state_after=state["checksum"],
                                  details={"note": "an interrupted transition was discarded"})
                log.warning("recovered from an interrupted transition")
            before = state["checksum"]
            new_state = copy.deepcopy(state)
            seq = len(self.audit.read()) + 1
            details = mutate(new_state, seq) or {}
            self._check_shape(new_state)
            new_state["revision"] = state["revision"] + 1
            new_state["updated_at"] = utc_now()
            new_state["checksum"] = checksum_of(new_state)
            self.audit.append(event, phase=phase, actor=actor, details=details, state_before=before,
                              state_after=new_state["checksum"])
            atomic_write_text(self.path, json.dumps(new_state, indent=2, sort_keys=True) + "\n")
            return new_state


# ======================================================================================
# Artifact validation
# ======================================================================================
class ArtifactChecker:
    def __init__(self, root: Path, workflow: Workflow) -> None:
        self.root, self.workflow = root, workflow

    def hash_outputs(self, phase: Phase) -> dict[str, str]:
        hashes = {}
        for rel in phase.output_paths:
            path = self.root / rel
            if path.is_file() and not path.is_symlink():
                hashes[rel] = sha256_file(path)
        return hashes

    def existing_outputs(self, phase: Phase) -> list[str]:
        return [rel for rel in phase.output_paths if (self.root / rel).exists() or (self.root / rel).is_symlink()]

    def read_output(self, phase: Phase) -> str:
        return (self.root / phase.output_paths[0]).read_text(encoding="utf-8")

    def validate_outputs(self, phase: Phase) -> list[Issue]:
        issues: list[Issue] = []
        for spec in phase.outputs:
            issues.extend(self._validate_one(phase, spec))
        return issues

    def _validate_one(self, phase: Phase, spec: OutputSpec) -> list[Issue]:
        rel, path = spec.path, self.root / spec.path
        if path.is_symlink():
            return [Issue("symlink", "symbolic links are not allowed as artifacts", rel, phase.id)]
        if not path.is_file():
            return [Issue("missing-output", "required output file does not exist", rel, phase.id)]
        size = path.stat().st_size
        if size < spec.min_bytes:
            return [Issue("too-small", f"{size} bytes; minimum is {spec.min_bytes}", rel, phase.id)]
        if size > spec.max_bytes:
            return [Issue("too-large", f"{size} bytes; maximum is {spec.max_bytes}", rel, phase.id)]
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return [Issue("not-utf8", "file is not valid UTF-8", rel, phase.id)]
        issues: list[Issue] = []
        sections = spec.required_sections + (spec.mcp_sections if self.workflow.mcp_enabled else ())
        patterns = spec.required_patterns + (spec.mcp_patterns if self.workflow.mcp_enabled else ())
        for section in sections:
            if re.search(r"(?m)^\s*" + re.escape(section) + r"\s*$", text) is None:
                issues.append(Issue("missing-section", f"required section '{section}' not found", rel, phase.id))
        for pattern in patterns:
            if re.search(pattern, text) is None:
                issues.append(Issue("pattern-not-met", f"required content not found: /{pattern}/", rel, phase.id))
        placeholders = find_placeholders(text)
        if placeholders:
            issues.append(Issue("placeholder", f"unresolved placeholders: {', '.join(placeholders)}", rel, phase.id))
        secrets = find_secrets(text)
        if secrets:
            issues.append(Issue("secret-detected", f"possible secret ({', '.join(secrets)})", rel, phase.id))
        return issues

    def unowned_artifacts(self) -> list[Issue]:
        base = self.root / "artifacts"
        if not base.is_dir():
            return []
        issues = []
        for path in sorted(base.rglob("*")):
            if not (path.is_file() or path.is_symlink()):
                continue
            rel = path.relative_to(self.root).as_posix()
            first = path.relative_to(base).parts[0]
            if first == ARCHIVE_DIRNAME or path.name in {".gitkeep", ".DS_Store"}:
                continue
            if self.workflow.owner_of(rel) is None:
                issues.append(Issue("unowned-artifact", "file is not an output of any phase", rel))
        return issues


# ======================================================================================
# Engine
# ======================================================================================
ConfirmFn = Callable[[str], bool]
_INCOMPLETE_CODES = frozenset({"missing-output", "too-small", "missing-section", "pattern-not-met", "placeholder"})
_AGENT_TOKENS = frozenset({"copilot", "bot", "agent", "orchestrator", "claude", "gpt", "assistant", "automation", "guard"})
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,200}$")


@dataclass
class PhaseRow:
    id: str
    order: int
    name: str
    agent: str
    status: str
    approval: str
    notes: str


@dataclass
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues


class Orchestrator:
    def __init__(self, root: Path, confirm: ConfirmFn | None = None) -> None:
        self.root = root.resolve()
        self.confirm = confirm
        self.workflow = load_workflow(self.root / "sdlc" / "phases.json")
        self.lock_path = self.root / "sdlc" / ".lock"
        self.audit = AuditLog(self.root / "sdlc" / "audit.log.jsonl", self.lock_path)
        self.state = StateManager(self.root / "sdlc" / "state.json", self.audit, self.workflow, self.lock_path)
        self.checker = ArtifactChecker(self.root, self.workflow)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _status(state: dict[str, Any], pid: str) -> str:
        return state["phases"][pid]["status"]

    def _prereqs_met(self, state: dict[str, Any], phase: Phase) -> bool:
        return all(self._status(state, p) == Status.APPROVED.value for p in phase.prerequisites)

    def _require_prereqs(self, state: dict[str, Any], phase: Phase) -> None:
        missing = [p for p in phase.prerequisites if self._status(state, p) != Status.APPROVED.value]
        if missing:
            raise TransitionError(f"phase '{phase.id}' requires approved prerequisite phase(s): {', '.join(missing)}")

    def _validate_approver(self, approver: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._@-]{1,63}", approver or ""):
            raise ApprovalError("approver must be a human identifier (letters, digits, . _ @ -; 2-64 chars)")
        tokens = set(re.split(r"[._@-]+", approver.lower()))
        banned = tokens & (_AGENT_TOKENS | {p.agent for p in self.workflow.phases})
        if banned:
            raise ApprovalError(f"approver '{approver}' looks like an automated identity; a human must approve")
        return approver

    def _human_confirm(self, phrase: str, purpose: str) -> None:
        if self.confirm is None:
            raise ApprovalError(f"{purpose} requires interactive human confirmation, which is unavailable here")
        if not self.confirm(phrase):
            raise ApprovalError(f"{purpose} not confirmed; nothing was changed")

    def record_error(self, command: str, exc: Exception, phase: str | None = None) -> None:
        """Best-effort audit of a failed command; never raises, never writes to a broken log."""
        try:
            if not self.audit.verify():
                self.audit.append("command.error", phase=phase,
                                  details={"command": command, "error": type(exc).__name__, "message": str(exc)[:500]})
        except Exception:  # noqa: BLE001
            log.debug("could not record error event", exc_info=True)

    # ---------------------------------------------------------------- queries
    def active_phase(self) -> Phase | None:
        state, _ = self.state.load()
        for phase in self.workflow.phases:
            if self._status(state, phase.id) == Status.IN_PROGRESS.value:
                return phase
        return None

    def status(self) -> tuple[list[PhaseRow], bool]:
        state, interrupted = self.state.load()
        rows = []
        for phase in self.workflow.phases:
            ps = state["phases"][phase.id]
            notes = ""
            if ps["status"] == Status.APPROVED.value and ps.get("approval"):
                notes = f"approved by {ps['approval']['approver']}"
            elif ps["status"] == Status.NOT_STARTED.value and self._prereqs_met(state, phase):
                notes = "ready to start"
            elif ps["status"] == Status.STALE.value:
                notes = ps.get("stale_reason") or ""
            if ps.get("pr_authorization"):
                notes = f"PR authorized by {ps['pr_authorization']['authorized_by']}"
            rows.append(PhaseRow(phase.id, phase.order, phase.name, phase.agent, ps["status"], "human", notes))
        return rows, interrupted

    def current(self) -> dict[str, Any]:
        state, _ = self.state.load()
        for phase in self.workflow.phases:
            status = self._status(state, phase.id)
            if status == Status.APPROVED.value:
                continue
            actions = {
                "not_started": f"start it:  orchestrator.py start {phase.id}",
                "in_progress": f"agent '{phase.agent}' produces {', '.join(phase.output_paths)}, then: orchestrator.py submit {phase.id}",
                "awaiting_approval": f"a HUMAN reviews and runs: orchestrator.py approve {phase.id} --approver <you>",
                "stale": f"artifacts drifted; a HUMAN must run: orchestrator.py reopen {phase.id} --reason <why>",
            }
            can_start = phase.id if status == "not_started" and self._prereqs_met(state, phase) else None
            return {"complete": False, "current": phase.id, "agent": phase.agent, "status": status,
                    "can_start": can_start, "next_action": actions[status]}
        return {"complete": True, "current": None, "agent": None, "status": None, "can_start": None,
                "next_action": "all phases approved; the pipeline is complete"}

    # ---------------------------------------------------------------- transitions
    def init(self, actor: str | None = None) -> None:
        self.state.initialize(actor)

    def start(self, phase_id: str, actor: str | None = None) -> None:
        phase = self.workflow.phase(phase_id)

        def mutate(state: dict[str, Any], seq: int) -> None:
            status = self._status(state, phase.id)
            if status != Status.NOT_STARTED.value:
                hint = " Use 'reopen' (human) to restart a stale or approved phase." if status in ("stale", "approved") else ""
                raise TransitionError(f"phase '{phase.id}' is '{status}', not 'not_started'.{hint}")
            self._require_prereqs(state, phase)
            leftovers = self.checker.existing_outputs(phase)
            if leftovers:
                raise TransitionError(f"phase '{phase.id}' already has output files ({', '.join(leftovers)}); "
                                      "remove or archive them before starting")
            (self.root / "artifacts").mkdir(parents=True, exist_ok=True)
            ps = blank_phase_state()
            ps.update(status=Status.IN_PROGRESS.value, started_at=utc_now(), started_seq=seq)
            state["phases"][phase.id] = ps

        self.state.apply("phase.started", mutate, phase=phase.id, actor=actor)

    def submit(self, phase_id: str, actor: str | None = None) -> str:
        phase = self.workflow.phase(phase_id)

        def mutate(state: dict[str, Any], seq: int) -> dict[str, Any]:
            status = self._status(state, phase.id)
            if status != Status.IN_PROGRESS.value:
                raise TransitionError(f"phase '{phase.id}' is '{status}'; only an 'in_progress' phase can be submitted")
            self._require_prereqs(state, phase)
            issues = self.checker.validate_outputs(phase)
            if not issues:
                issues = self._check_evidence(phase, state)
            if issues:
                raise ValidationFailed(f"phase '{phase.id}' failed validation", issues)
            ps = state["phases"][phase.id]
            ps["artifact_hashes"] = self.checker.hash_outputs(phase)
            ps["submitted_at"] = utc_now()
            ps["status"] = Status.AWAITING_APPROVAL.value  # only a human can move a phase to approved
            return {"artifact_hashes": ps["artifact_hashes"], "result": ps["status"]}

        return self.state.apply("phase.submitted", mutate, phase=phase.id, actor=actor)["phases"][phase.id]["status"]

    def approve(self, phase_id: str, approver: str, comment: str = "", actor: str | None = None) -> None:
        phase = self.workflow.phase(phase_id)
        approver = self._validate_approver(approver)

        def mutate(state: dict[str, Any], seq: int) -> dict[str, Any]:
            status = self._status(state, phase.id)
            if status != Status.AWAITING_APPROVAL.value:
                raise TransitionError(f"phase '{phase.id}' is '{status}'; only 'awaiting_approval' can be approved")
            self._require_prereqs(state, phase)
            ps = state["phases"][phase.id]
            stored, current = ps["artifact_hashes"], self.checker.hash_outputs(phase)
            if current != stored:
                raise TransitionError(f"artifacts changed after submission; re-run 'submit {phase.id}' so the "
                                      "reviewer approves the exact content")
            issues = self.checker.validate_outputs(phase) or self._check_evidence(phase, state)
            if issues:
                raise ValidationFailed(f"phase '{phase.id}' no longer validates", issues)
            self._human_confirm(f"APPROVE {phase.id}", f"approval of '{phase.id}'")  # last gate, right before the write
            ps["status"] = Status.APPROVED.value
            ps["approval"] = {"approver": approver, "method": "human-confirmation", "approved_at": utc_now(),
                              "comment": comment, "approved_hashes": dict(stored)}
            return {"approver": approver, "approved_hashes": dict(stored), "comment": comment}

        self.state.apply("phase.approved", mutate, phase=phase.id, actor=actor or approver)

    def reject(self, phase_id: str, reason: str, actor: str | None = None) -> None:
        phase = self.workflow.phase(phase_id)
        if not reason.strip():
            raise TransitionError("a rejection reason is required")

        def mutate(state: dict[str, Any], seq: int) -> dict[str, Any]:
            status = self._status(state, phase.id)
            if status != Status.AWAITING_APPROVAL.value:
                raise TransitionError(f"phase '{phase.id}' is '{status}'; only 'awaiting_approval' can be rejected")
            ps = state["phases"][phase.id]
            ps.update(status=Status.IN_PROGRESS.value, artifact_hashes={}, submitted_at=None)
            return {"reason": reason}

        self.state.apply("phase.rejected", mutate, phase=phase.id, actor=actor)

    def reopen(self, phase_id: str, reason: str, actor: str | None = None) -> list[str]:
        """Reopen a phase; later phases are reset and their artifacts archived (never deleted)."""
        phase = self.workflow.phase(phase_id)
        if not reason.strip():
            raise TransitionError("a reopen reason is required")
        with file_lock(self.lock_path):
            state, _ = self.state.load()
            status = self._status(state, phase.id)
            if status in (Status.NOT_STARTED.value, Status.IN_PROGRESS.value):
                raise TransitionError(f"phase '{phase.id}' is '{status}'; only submitted, approved, or stale phases can be reopened")
            downstream = self.workflow.downstream(phase.id)
            files = [f for d in downstream for f in self.checker.existing_outputs(d)]
            self._human_confirm(f"REOPEN {phase.id}", f"reopening '{phase.id}'")
            archive_dir: str | None = None
            archived: list[str] = []
            if files:
                stamp = utc_now().replace(":", "").replace("-", "")
                dest_root = self.root / "artifacts" / ARCHIVE_DIRNAME / f"{stamp}-reopen-{phase.id}"
                for rel in files:
                    dest = dest_root / Path(rel).name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(self.root / rel, dest)
                    archived.append(rel)
                archive_dir = dest_root.relative_to(self.root).as_posix()

            def mutate(new: dict[str, Any], seq: int) -> dict[str, Any]:
                ps = new["phases"][phase.id]
                ps.update(status=Status.IN_PROGRESS.value, artifact_hashes={}, approval=None, submitted_at=None,
                          stale_reason=None, pr_authorization=None, started_seq=seq)
                for d in downstream:
                    new["phases"][d.id] = blank_phase_state()
                return {"reason": reason, "previous_status": status, "reset_phases": [d.id for d in downstream],
                        "archived_files": archived, "archive_dir": archive_dir}

            self.state.apply("phase.reopened", mutate, phase=phase.id, actor=actor)
            for rel in archived:  # originals are removed only after the state change is durable
                with contextlib.suppress(OSError):
                    (self.root / rel).unlink()
        return archived

    def revalidate(self, phase_id: str | None = None, actor: str | None = None) -> tuple[list[str], dict[str, str], list[Issue]]:
        """Re-hash submitted/approved artifacts. Drift marks that phase and every later phase 'stale'."""
        with file_lock(self.lock_path):
            state, _ = self.state.load()
            targets = [self.workflow.phase(phase_id)] if phase_id else list(self.workflow.phases)
            checked: list[str] = []
            drifted: dict[str, str] = {}
            issues: list[Issue] = []
            for phase in targets:
                if self._status(state, phase.id) not in (Status.AWAITING_APPROVAL.value, Status.APPROVED.value):
                    continue
                checked.append(phase.id)
                reason = self._hash_drift(state, phase)
                if reason:
                    drifted[phase.id] = reason
                else:
                    issues += self.checker.validate_outputs(phase) + self._check_evidence(phase, state)
            if drifted:
                first = min(drifted, key=lambda p: self.workflow.phase(p).order)
                first_order = self.workflow.phase(first).order

                def mutate(new: dict[str, Any], seq: int) -> dict[str, Any]:
                    for ph in self.workflow.phases:
                        entry = new["phases"][ph.id]
                        if ph.order >= first_order and entry["status"] != Status.NOT_STARTED.value:
                            entry["status"] = Status.STALE.value
                            entry["stale_reason"] = drifted.get(ph.id) or f"upstream phase '{first}' is stale"
                    return {"drifted": drifted}

                self.state.apply("revalidate.drift", mutate, phase=first, actor=actor)
            else:
                self.audit.append("revalidate.ok", phase=phase_id, actor=actor,
                                  details={"checked": checked, "issue_count": len(issues)})
            return checked, drifted, issues

    def _hash_drift(self, state: dict[str, Any], phase: Phase) -> str | None:
        stored, current = state["phases"][phase.id]["artifact_hashes"], self.checker.hash_outputs(phase)
        if stored == current:
            return None
        parts = []
        changed = sorted(k for k in stored if k in current and stored[k] != current[k])
        missing, added = sorted(set(stored) - set(current)), sorted(set(current) - set(stored))
        if changed:
            parts.append("modified: " + ", ".join(changed))
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if added:
            parts.append("unexpected: " + ", ".join(added))
        return "; ".join(parts)

    # ---------------------------------------------------------------- verification evidence
    def run_checks(self, actor: str | None = None, timeout: int = 900) -> dict[str, Any]:
        """Run the real test suite for the Verification phase and record tamper-evident evidence."""
        state, _ = self.state.load()
        if self._status(state, "verify") != Status.IN_PROGRESS.value:
            raise TransitionError("run-checks is only available while the 'verify' phase is in progress")
        command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
        before = source_digest(self.root, self.workflow.source_globs)
        started = time.monotonic()
        try:
            proc = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=timeout,
                                  env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, check=False)
            exit_code, output = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
        except subprocess.TimeoutExpired:
            exit_code, output = 124, f"timed out after {timeout}s"
        duration = round(time.monotonic() - started, 2)
        after = source_digest(self.root, self.workflow.source_globs)
        if before != after:
            raise ValidationFailed("source files changed while the checks were running; re-run 'run-checks'")

        def count(word: str) -> int:
            match = re.search(rf"(\d+) {word}", output)
            return int(match.group(1)) if match else 0

        tail = output.strip()[-2000:]
        details = {"command": " ".join(["python", "-m", "pytest", "-q", "tests"]), "exit_code": exit_code,
                   "passed": count("passed"), "failed": count("failed"), "errors": count("error"),
                   "duration_s": duration, "source_digest": after,
                   "output_tail": "[withheld: possible secret]" if find_secrets(tail) else tail}
        entry = self.audit.append("checks.run", phase="verify", actor=actor, details=details)
        return {"seq": entry["seq"], **details}

    # ---------------------------------------------------------------- pull-request authorization
    def authorize_pr(self, repo: str, head: str, base: str, approver: str, actor: str | None = None) -> None:
        """HUMAN ONLY: authorize creating exactly one pull request through the GitHub MCP server."""
        if not self.workflow.mcp_enabled:
            raise TransitionError("MCP integrations are disabled; set integrations.mcp_evidence to true in "
                                  "sdlc/phases.json before authorizing a pull request")
        phase = self.workflow.phase("pr")
        if not _REPO_RE.match(repo or ""):
            raise TransitionError("repository must look like 'owner/name'")
        if not (_REF_RE.match(head or "") and _REF_RE.match(base or "")) or head == base:
            raise TransitionError("head and base must be distinct, valid branch names")
        if head in ("main", "master"):
            raise TransitionError("the head branch must be a feature branch, not main/master")
        approver = self._validate_approver(approver)

        def mutate(state: dict[str, Any], seq: int) -> dict[str, Any]:
            status = self._status(state, phase.id)
            if status != Status.IN_PROGRESS.value:
                raise TransitionError(f"phase 'pr' is '{status}'; authorize while it is 'in_progress'")
            self._require_prereqs(state, phase)
            issues = self.checker.validate_outputs(phase)
            if issues:
                raise ValidationFailed("pr.md must be complete and valid before authorization", issues)
            text = self.checker.read_output(phase)
            declared = {k: (re.search(rf"(?m)^{k}:\s*(\S+)\s*$", text) or [None, None])[1] for k in ("Repository", "Head", "Base")}
            if declared != {"Repository": repo, "Head": head, "Base": base}:
                raise TransitionError(f"arguments do not match pr.md (Repository/Head/Base = {declared})")
            self._human_confirm(f"AUTHORIZE PR {repo} {head} {base}", "pull-request authorization")
            digest = pr_body_digest(text)
            state["phases"][phase.id]["pr_authorization"] = {
                "repo": repo, "head": head, "base": base, "authorized_by": approver, "authorized_at": utc_now(),
                "body_digest": digest, "audit_seq": seq}
            return {"repo": repo, "head": head, "base": base, "authorized_by": approver, "body_digest": digest}

        self.state.apply("pr.authorized", mutate, phase=phase.id, actor=actor or approver)

    def pr_creation_check(self, args: dict[str, Any]) -> tuple[bool, str]:
        """Used by the guard: may the agent call create_pull_request with these arguments right now?"""
        state, _ = self.state.load()
        phase = self.workflow.phase("pr")
        if not self.workflow.mcp_enabled:
            return False, "MCP integrations are disabled (sdlc/phases.json: integrations.mcp_evidence)"
        if self._status(state, "pr") != Status.IN_PROGRESS.value:
            return False, "pull requests can only be created while the 'pr' phase is in progress"
        auth = state["phases"]["pr"].get("pr_authorization")
        if not auth:
            return False, "no human authorization: a human must run 'orchestrator.py authorize-pr' first"
        owner, repo = str(args.get("owner", "")), str(args.get("repo", ""))
        if f"{owner}/{repo}" != auth["repo"] or str(args.get("head", "")) != auth["head"] \
                or str(args.get("base", "")) != auth["base"]:
            return False, "arguments differ from the authorized repository/head/base"
        try:
            if pr_body_digest(self.checker.read_output(phase)) != auth["body_digest"]:
                return False, "pr.md changed after authorization; a human must re-authorize"
        except (OSError, UnicodeDecodeError):
            return False, "pr.md is unreadable"
        for entry in self.audit.read():
            if entry["seq"] > auth["audit_seq"] and entry["event"] == "mcp.call" \
                    and entry["details"].get("kind") == "github_pr_created" and not entry["details"].get("is_error"):
                return False, "the authorized pull request was already created (authorization is single-use)"
        return True, ""

    # ---------------------------------------------------------------- evidence checks
    def _evidence_entries(self, text: str, label: str) -> list[int]:
        return [int(x) for x in re.findall(rf"(?m)^{re.escape(label)}:\s*(\d+)\s*$", text)]

    def _check_evidence(self, phase: Phase, state: dict[str, Any]) -> list[Issue]:
        if phase.evidence is None:
            return []
        if phase.evidence in ("confluence", "github_pr") and not self.workflow.mcp_enabled:
            return []  # MCP integrations are switched off in sdlc/phases.json (integrations.mcp_evidence)
        ps = state["phases"][phase.id]
        started = ps.get("started_seq") or 0
        entries = {e["seq"]: e for e in self.audit.read()}
        rel = phase.output_paths[0]
        try:
            text = self.checker.read_output(phase)
        except (OSError, UnicodeDecodeError):
            return [Issue("missing-output", "cannot read output for evidence checks", rel, phase.id)]

        def issue(msg: str) -> Issue:
            return Issue("evidence", msg, rel, phase.id)

        issues: list[Issue] = []
        if phase.evidence == "confluence":
            ids = self._evidence_entries(text, "Evidence-ID")
            urls: set[str] = set()
            valid = 0
            for seq in ids:
                e = entries.get(seq)
                d = (e or {}).get("details", {})
                if not e or e["event"] != "mcp.call" or d.get("kind") != "confluence":
                    issues.append(issue(f"Evidence-ID {seq} is not a recorded Confluence MCP call"))
                elif seq <= started:
                    issues.append(issue(f"Evidence-ID {seq} predates the start of this phase"))
                elif d.get("is_error") or d.get("result_chars", 0) < MIN_EVIDENCE_CHARS:
                    issues.append(issue(f"Evidence-ID {seq} returned no usable content"))
                else:
                    valid += 1
                    urls.update(d.get("urls", []))
            if not valid:
                issues.append(issue("no valid Confluence MCP evidence: fetch the user stories with the Atlassian MCP "
                                    "tools first, then cite the audit sequence number as 'Evidence-ID: <n>'"))
            for url in re.findall(r"(?m)^Confluence-URL:\s*(\S+)\s*$", text):
                if url not in urls:
                    issues.append(issue(f"Confluence-URL {url} was not returned by any cited MCP call"))
        elif phase.evidence == "checks":
            current = source_digest(self.root, self.workflow.source_globs)
            good = False
            for seq in self._evidence_entries(text, "Evidence-ID"):
                e = entries.get(seq)
                d = (e or {}).get("details", {})
                if e and e["event"] == "checks.run" and seq > started and d.get("exit_code") == 0 \
                        and d.get("passed", 0) >= 1 and d.get("failed", 1) == 0 and d.get("errors", 1) == 0:
                    if d.get("source_digest") == current:
                        good = True
                    else:
                        issues.append(issue(f"Evidence-ID {seq}: source changed since the tests ran; run 'run-checks' again"))
            if not good and not issues:
                issues.append(issue("no passing 'orchestrator.py run-checks' evidence found; run it and cite the "
                                    "sequence number as 'Evidence-ID: <n>'"))
        elif phase.evidence == "github_pr":
            auth = ps.get("pr_authorization")
            if not auth:
                return [issue("no human authorization recorded; a human must run 'orchestrator.py authorize-pr'")]
            if pr_body_digest(text) != auth["body_digest"]:
                issues.append(issue("pr.md changed after authorization; a human must re-authorize"))
            url_m = re.search(rf"(?m)^PR-URL:\s*(https://github\.com/{re.escape(auth['repo'])}/pull/\d+)\s*$", text)
            ids = self._evidence_entries(text, "PR-Evidence-ID")
            if not url_m or not ids:
                issues.append(issue("pr.md must contain 'PR-URL: <url>' and 'PR-Evidence-ID: <n>' for the created pull request"))
            else:
                ok = False
                for seq in ids:
                    e = entries.get(seq)
                    d = (e or {}).get("details", {})
                    if e and e["event"] == "mcp.call" and d.get("kind") == "github_pr_created" and not d.get("is_error") \
                                                        and seq > auth["audit_seq"] and (not d.get("urls") or url_m.group(1) in d.get("urls", [])) \
                            and d.get("target") == f"{auth['repo']} {auth['head']} {auth['base']}" \
                            and d.get("pr_body_digest") == auth["body_digest"]:
                        ok = True
                if not ok:
                    issues.append(issue("PR-Evidence-ID does not match a create_pull_request call made after authorization "
                                        "for the authorized repository, branches, and PR content"))
        return issues

    # ---------------------------------------------------------------- pipeline validation
    def validate(self) -> ValidationReport:
        report = ValidationReport()
        state, interrupted = self.state.load()
        if interrupted:
            report.warnings.append("an interrupted transition was detected; the next state change discards it")
        for phase in self.workflow.phases:
            ps = state["phases"][phase.id]
            status = ps["status"]
            if status != Status.NOT_STARTED.value and not self._prereqs_met(state, phase):
                report.issues.append(Issue("order-violation", f"phase is '{status}' but prerequisites are not approved", phase=phase.id))
            if status == Status.NOT_STARTED.value:
                for rel in self.checker.existing_outputs(phase):
                    report.issues.append(Issue("premature-artifact", "artifact exists before the phase started", rel, phase.id))
            elif status == Status.IN_PROGRESS.value:
                report.issues += [i for i in self.checker.validate_outputs(phase) if i.code not in _INCOMPLETE_CODES]
            elif status == Status.STALE.value:
                report.issues.append(Issue("stale-phase", ps.get("stale_reason") or "phase is stale; reopen it", phase=phase.id))
            else:
                if set(ps["artifact_hashes"]) != set(phase.output_paths):
                    report.issues.append(Issue("hashes-incomplete", "recorded hashes do not cover every output", phase=phase.id))
                drift = self._hash_drift(state, phase)
                if drift:
                    report.issues.append(Issue("hash-mismatch", f"artifacts changed since submission ({drift})", phase=phase.id))
                else:
                    report.issues += self.checker.validate_outputs(phase) + self._check_evidence(phase, state)
                if status == Status.APPROVED.value:
                    approval = ps.get("approval") or {}
                    if not approval:
                        report.issues.append(Issue("approval-missing", "approved without an approval record", phase=phase.id))
                    elif (approval.get("method") != "human-confirmation"
                          or approval.get("approved_hashes") != ps["artifact_hashes"]):
                        report.issues.append(Issue("approval-invalid", "human approval missing or bound to different content", phase=phase.id))
        report.issues += self.checker.unowned_artifacts()
        return report


# ======================================================================================
# CLI
# ======================================================================================
def tty_confirm(phrase: str) -> bool:
    """Human gate: requires an interactive terminal and the exact phrase typed by the person."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ApprovalError("human confirmation requires an interactive terminal; run this command yourself in a "
                            "terminal, not through an agent, script, or pipe")
    sys.stdout.write(f"Type exactly '{phrase}' to confirm (anything else cancels): ")
    sys.stdout.flush()
    return sys.stdin.readline().strip() == phrase


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="orchestrator.py", description="Agentic SDLC orchestrator")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--root", type=Path, default=None, help="repository root (default: this file's directory)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging to stderr")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")
    sub.add_parser("init", help="HUMAN ONLY: create initial state and audit log (fresh repository)")
    sub.add_parser("status", help="show every phase and its status")
    sub.add_parser("current", help="show the current phase and the next action")
    sub.add_parser("validate", help="validate state, ordering, artifacts, evidence, and ownership")
    sub.add_parser("run-checks", help="run the test suite and record verification evidence")
    d = sub.add_parser("describe", help="show a phase contract")
    d.add_argument("phase")
    for name, text in (("start", "begin a phase"), ("submit", "validate outputs and submit a phase")):
        s = sub.add_parser(name, help=text)
        s.add_argument("phase")
    a = sub.add_parser("approve", help="HUMAN ONLY: approve a submitted phase")
    a.add_argument("phase")
    a.add_argument("--approver", required=True, help="your human identifier, e.g. a GitHub username")
    a.add_argument("--comment", default="")
    r = sub.add_parser("reject", help="return a submitted phase to in_progress")
    r.add_argument("phase")
    r.add_argument("--reason", required=True)
    o = sub.add_parser("reopen", help="HUMAN ONLY: reopen a phase; later phases are reset and archived")
    o.add_argument("phase")
    o.add_argument("--reason", required=True)
    v = sub.add_parser("revalidate", help="re-hash submitted/approved artifacts; drift marks phases stale")
    v.add_argument("phase", nargs="?", default=None)
    z = sub.add_parser("authorize-pr", help="HUMAN ONLY: authorize one pull request via GitHub MCP")
    z.add_argument("--repo", required=True, help="owner/name")
    z.add_argument("--head", required=True)
    z.add_argument("--base", required=True)
    z.add_argument("--approver", required=True)
    u = sub.add_parser("audit", help="show recent audit entries and verify the hash chain")
    u.add_argument("--tail", type=int, default=20, help="entries to show (0 = all)")
    u.add_argument("--event", default=None, help="only show this event type, e.g. mcp.call")
    return p


def _out(args: argparse.Namespace, payload: Any, text: str) -> None:
    print(json.dumps(payload, indent=2) if args.json else text)


def _print_issues(issues: Sequence[Issue]) -> None:
    for issue in issues:
        print(f"  - {issue}", file=sys.stderr)


def dispatch(orch: Orchestrator, args: argparse.Namespace) -> int:
    cmd, actor = args.command, current_user()
    if cmd == "init":
        orch.init(actor)
        _out(args, {"initialized": True}, "initialized sdlc/state.json and the audit log")
    elif cmd == "status":
        rows, interrupted = orch.status()
        lines = [f"{'#':<3}{'PHASE':<16}{'STATUS':<19}{'APPROVAL':<10}{'AGENT':<16}NOTES"]
        lines += [f"{r.order:<3}{r.id:<16}{r.status:<19}{r.approval:<10}{r.agent:<16}{r.notes}" for r in rows]
        if interrupted:
            lines.append("warning: an interrupted transition was detected; the next state change discards it")
        _out(args, {"phases": [r.__dict__ for r in rows], "interrupted_transition": interrupted}, "\n".join(lines))
    elif cmd == "current":
        info = orch.current()
        text = info["next_action"] if info["complete"] else (
            f"current phase : {info['current']} ({info['status']}, agent: {info['agent']})\n"
            f"can start now : {info['can_start'] or '-'}\nnext action   : {info['next_action']}")
        _out(args, info, text)
    elif cmd == "describe":
        ph = orch.workflow.phase(args.phase)
        info = {"id": ph.id, "name": ph.name, "agent": ph.agent, "purpose": ph.purpose,
                "prerequisites": list(ph.prerequisites), "consumes": list(ph.consumes),
                "external_inputs": list(ph.external_inputs), "outputs": list(ph.output_paths),
                "validation_rules": list(ph.validation_rules), "completion_conditions": list(ph.completion_conditions),
                "approval": "human", "evidence": ph.evidence,
                "write_globs": list(ph.write_globs)}
        lines = [f"{ph.order}. {ph.name} (agent: {ph.agent})", f"purpose: {ph.purpose}"]
        for key in ("prerequisites", "consumes", "external_inputs", "outputs", "validation_rules",
                    "completion_conditions", "write_globs"):
            lines.append(f"{key}:")
            lines += [f"  - {v}" for v in info[key]] or ["  (none)"]
        lines.append(f"approval: {info['approval']}   evidence: {info['evidence'] or 'none'}")
        if ph.evidence in ("confluence", "github_pr") and not orch.workflow.mcp_enabled:
            lines.append("note: MCP evidence is disabled (integrations.mcp_evidence = false); only the base rules apply")
        _out(args, info, "\n".join(lines))
    elif cmd == "validate":
        report = orch.validate()
        if args.json:
            print(json.dumps({"ok": report.ok, "issues": [i.as_dict() for i in report.issues],
                              "warnings": report.warnings}, indent=2))
        else:
            for w in report.warnings:
                print(f"warning: {w}", file=sys.stderr)
            if report.ok:
                print("validation passed")
            else:
                print(f"validation FAILED ({len(report.issues)} issue(s)):", file=sys.stderr)
                _print_issues(report.issues)
        return ExitCode.OK if report.ok else ExitCode.VALIDATION_FAILED
    elif cmd == "start":
        orch.start(args.phase, actor)
        _out(args, {"phase": args.phase, "status": "in_progress"}, f"phase '{args.phase}' started")
    elif cmd == "submit":
        status = orch.submit(args.phase, actor)
        _out(args, {"phase": args.phase, "status": status}, f"phase '{args.phase}' submitted; awaiting human approval")
    elif cmd == "approve":
        orch.approve(args.phase, args.approver, args.comment, actor)
        _out(args, {"phase": args.phase, "status": "approved", "approver": args.approver},
             f"phase '{args.phase}' approved by {args.approver}")
    elif cmd == "reject":
        orch.reject(args.phase, args.reason, actor)
        _out(args, {"phase": args.phase, "status": "in_progress"}, f"phase '{args.phase}' returned to in_progress")
    elif cmd == "reopen":
        archived = orch.reopen(args.phase, args.reason, actor)
        _out(args, {"phase": args.phase, "archived": archived},
             f"phase '{args.phase}' reopened; {len(archived)} downstream file(s) archived under artifacts/_archive/")
    elif cmd == "revalidate":
        checked, drifted, issues = orch.revalidate(args.phase, actor)
        if args.json:
            print(json.dumps({"checked": checked, "drifted": drifted, "issues": [i.as_dict() for i in issues]}, indent=2))
        elif not drifted and not issues:
            print(f"revalidated {len(checked)} phase(s): no drift")
        else:
            for pid, reason in drifted.items():
                print(f"DRIFT in '{pid}': {reason}", file=sys.stderr)
            if drifted:
                print("affected phases are now 'stale'; a human must run 'reopen'", file=sys.stderr)
            _print_issues(issues)
        return ExitCode.OK if not drifted and not issues else ExitCode.VALIDATION_FAILED
    elif cmd == "run-checks":
        result = orch.run_checks(actor)
        _out(args, result, f"checks.run recorded as Evidence-ID {result['seq']}: exit={result['exit_code']} "
                           f"passed={result['passed']} failed={result['failed']} errors={result['errors']}\n"
                           f"{result['output_tail']}")
        return ExitCode.OK if result["exit_code"] == 0 else ExitCode.VALIDATION_FAILED
    elif cmd == "authorize-pr":
        orch.authorize_pr(args.repo, args.head, args.base, args.approver, actor)
        _out(args, {"authorized": True, "repo": args.repo, "head": args.head, "base": args.base},
             f"authorized ONE pull request: {args.repo} {args.head} -> {args.base}")
    elif cmd == "audit":
        problems = orch.audit.verify()
        entries = [] if problems else orch.audit.read()
        if args.event:
            entries = [e for e in entries if e["event"] == args.event]
        entries = entries[-args.tail:] if args.tail > 0 else entries
        if args.json:
            print(json.dumps({"intact": not problems, "problems": problems, "entries": entries}, indent=2))
        else:
            for e in entries:
                print(f"{e['seq']:>5}  {e['ts']}  {e['event']:<20} {e.get('phase') or '-':<14} {e['actor']}")
            print("audit chain INTACT" if not problems else "audit log INTEGRITY FAILURE:\n  - " + "\n  - ".join(problems))
        return ExitCode.OK if not problems else ExitCode.STATE_ERROR
    return ExitCode.OK


MUTATING = frozenset({"init", "start", "submit", "approve", "reject", "reopen", "revalidate", "run-checks", "authorize-pr"})


def main(argv: Sequence[str] | None = None, default_root: Path | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    root = (args.root or default_root or ROOT).resolve()
    orch: Orchestrator | None = None
    try:
        orch = Orchestrator(root, confirm=tty_confirm)
        return int(dispatch(orch, args))
    except OrchestratorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if isinstance(exc, ValidationFailed):
            _print_issues(exc.issues)
        if orch is not None and args.command in MUTATING:
            orch.record_error(args.command, exc, getattr(args, "phase", None))
        return int(exc.exit_code)
    except OSError as exc:
        log.debug("I/O failure", exc_info=True)
        print(f"error: I/O failure: {exc}", file=sys.stderr)
        return int(ExitCode.IO_ERROR)
    except KeyboardInterrupt:
        print("interrupted; no partial state was written", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
