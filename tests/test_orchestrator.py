"""Tests for orchestrator.py. Every test runs in a temporary copy of the workflow; the real sdlc/ state is never touched."""
 
from __future__ import annotations
 
import json
from pathlib import Path
from typing import Callable
 
import pytest
 
import orchestrator as orc
from orchestrator import (ApprovalError, ExitCode, Orchestrator, StateError, TransitionError, ValidationFailed)
 
REPO = Path(__file__).resolve().parent.parent
URL = "https://example.atlassian.net/wiki/spaces/APP/pages/12345"
PR_URL = "https://github.com/acme/todo-app/pull/7"
PR_HEADER = "Repository: acme/todo-app\nHead: feature/todo\nBase: main"
 
 
# ------------------------------------------------------------------------------ helpers
def _workspace(tmp_path: Path, *, mcp: bool) -> Path:
    (tmp_path / "sdlc").mkdir()
    (tmp_path / "artifacts").mkdir()
    data = json.loads((REPO / "sdlc" / "phases.json").read_text(encoding="utf-8"))
    data["integrations"] = {"mcp_evidence": mcp}
    (tmp_path / "sdlc" / "phases.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """Workflow copy with the MCP evidence switch ON (the repository ships with it OFF)."""
    return _workspace(tmp_path, mcp=True)
 
 
@pytest.fixture()
def plain_root(tmp_path: Path) -> Path:
    """Workflow copy exactly as shipped: MCP evidence OFF."""
    return _workspace(tmp_path, mcp=False)
 
 
def make(root: Path, confirm: Callable[[str], bool] | None = lambda phrase: True) -> Orchestrator:
    return Orchestrator(root, confirm=confirm)
 
 
@pytest.fixture()
def orch(root: Path) -> Orchestrator:
    o = make(root)
    o.init("tester")
    return o
 
 
def audit_event(orch: Orchestrator, event: str, **details: object) -> int:
    return orch.audit.append(event, actor="guard", details=dict(details))["seq"]
 
 
def mcp_confluence(orch: Orchestrator, urls: list[str] | None = None, chars: int = 800) -> int:
    return audit_event(orch, "mcp.call", kind="confluence", tool="atlassian/getConfluencePage", is_error=False,
                       result_chars=chars, urls=urls if urls is not None else [URL])
 
 
def write_artifact(root: Path, orch: Orchestrator, pid: str, extra: str = "", body: str = "") -> Path:
    spec = orch.workflow.phase(pid).outputs[0]
    lines = [extra, ""] if extra else []
    for section in spec.required_sections + (spec.mcp_sections if orch.workflow.mcp_enabled else ()):
        lines += [section, "", body or "This section describes the work for the phase in concrete terms. " * 2, ""]
    text = "\n".join(lines)
    while len(text.encode()) < spec.min_bytes:
        text += "Additional supporting detail for the reviewer. "
    path = root / spec.path
    path.write_text(text + "\n", encoding="utf-8")
    return path
 
 
def extra_for(orch: Orchestrator, root: Path, pid: str) -> str:
    if pid == "requirements":
        return f"Confluence-URL: {URL}\nEvidence-ID: {mcp_confluence(orch)}"
    if pid in ("design-review", "review"):
        return "Verdict: APPROVED"
    if pid == "verify":
        seq = audit_event(orch, "checks.run", exit_code=0, passed=3, failed=0, errors=0,
                          source_digest=orc.source_digest(root, orch.workflow.source_globs))
        return f"Verdict: PASS\nEvidence-ID: {seq}"
    if pid == "pr":
        return PR_HEADER
    return ""
 
 
def run_phase(orch: Orchestrator, root: Path, pid: str) -> None:
    orch.start(pid)
    write_artifact(root, orch, pid, extra_for(orch, root, pid))
    if orch.submit(pid) == "awaiting_approval":
        orch.approve(pid, "alice")
 
 
def run_pr(orch: Orchestrator, root: Path) -> None:
    orch.start("pr")
    path = write_artifact(root, orch, "pr", PR_HEADER)
    orch.authorize_pr("acme/todo-app", "feature/todo", "main", "alice")
    seq = audit_event(orch, "mcp.call", kind="github_pr_created", tool="create_pull_request", is_error=False,
                      result_chars=300, urls=[PR_URL], target="acme/todo-app feature/todo main",
                      pr_body_digest=orc.pr_body_digest(path.read_text(encoding="utf-8")))
    path.write_text(path.read_text(encoding="utf-8") + f"\nPR-URL: {PR_URL}\nPR-Evidence-ID: {seq}\n", encoding="utf-8")
    orch.submit("pr")
    orch.approve("pr", "alice")
 
 
def advance(orch: Orchestrator, root: Path, upto: str) -> None:
    """Approve every phase before `upto`."""
    for pid in orch.workflow.ids:
        if pid == upto:
            return
        run_phase(orch, root, pid)
 
 
def phase_status(orch: Orchestrator, pid: str) -> str:
    return orch.state.load()[0]["phases"][pid]["status"]
 
 
# ------------------------------------------------------------------------------ MCP switch (shipped default: OFF)
def test_repository_declares_the_mcp_evidence_switch_as_a_boolean() -> None:
    # The shipped value is a human decision (it was switched on for the Confluence run); only its type is fixed.
    raw = json.loads((REPO / "sdlc" / "phases.json").read_text(encoding="utf-8"))
    assert isinstance(raw["integrations"]["mcp_evidence"], bool)
 
 
def test_switch_must_be_a_boolean(tmp_path: Path) -> None:
    data = json.loads((REPO / "sdlc" / "phases.json").read_text(encoding="utf-8"))
    data["integrations"] = {"mcp_evidence": "yes"}
    with pytest.raises(orc.ConfigError):
        orc.parse_workflow(data)
 
 
def test_requirements_need_only_a_valid_artifact_and_approval_when_mcp_is_off(plain_root: Path) -> None:
    o = make(plain_root)
    o.init("tester")
    o.start("requirements")
    write_artifact(plain_root, o, "requirements")  # no Confluence-URL, no Evidence-ID, no Evidence section
    assert o.submit("requirements") == "awaiting_approval"
    o.approve("requirements", "alice")
    assert phase_status(o, "requirements") == "approved"
 
 
def test_pr_phase_needs_no_pull_request_evidence_when_mcp_is_off(plain_root: Path) -> None:
    o = make(plain_root)
    o.init("tester")
    for pid in o.workflow.ids[:-1]:
        run_phase(o, plain_root, pid)
    o.start("pr")
    write_artifact(plain_root, o, "pr")
    assert o.submit("pr") == "awaiting_approval"
    o.approve("pr", "alice")
    assert phase_status(o, "pr") == "approved"
 
 
def test_verify_still_needs_real_check_evidence_when_mcp_is_off(plain_root: Path) -> None:
    o = make(plain_root)
    o.init("tester")
    for pid in o.workflow.ids[:6]:
        run_phase(o, plain_root, pid)
    o.start("verify")
    write_artifact(plain_root, o, "verify", "Verdict: PASS\nEvidence-ID: 999")
    with pytest.raises(ValidationFailed):
        o.submit("verify")
 
 
def test_pull_request_authorization_is_refused_when_mcp_is_off(plain_root: Path) -> None:
    o = make(plain_root)
    o.init("tester")
    for pid in o.workflow.ids[:-1]:
        run_phase(o, plain_root, pid)
    o.start("pr")
    write_artifact(plain_root, o, "pr", PR_HEADER)
    with pytest.raises(TransitionError):
        o.authorize_pr("acme/todo-app", "feature/todo", "main", "alice")
    allowed, reason = o.pr_creation_check({"owner": "acme", "repo": "todo-app", "head": "feature/todo", "base": "main"})
    assert not allowed and "disabled" in reason
 
 
# ------------------------------------------------------------------------------ contract
def test_contract_has_eight_phases_in_order() -> None:
    wf = orc.load_workflow(REPO / "sdlc" / "phases.json")
    assert wf.ids == orc.PHASE_IDS
    assert [p.order for p in wf.phases] == list(range(1, 9))
    for p in wf.phases:
        assert all(wf.phase(q).order < p.order for q in p.prerequisites)
 
 
def test_every_agent_prompt_and_skill_exists_and_matches_the_contract() -> None:
    wf = orc.load_workflow(REPO / "sdlc" / "phases.json")
    for p in wf.phases:
        agent = (REPO / ".github" / "agents" / f"{p.agent}.agent.md").read_text(encoding="utf-8")
        prompt = (REPO / ".github" / "prompts" / f"{p.id}.prompt.md").read_text(encoding="utf-8")
        assert f"name: {p.agent}\n" in agent
        assert f"agent: {p.agent}\n" in prompt
    for skill in ("requirements", "verify", "pr"):
        assert f"name: {skill}\n" in (REPO / ".github" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
 
 
def test_only_the_right_agents_get_mcp_tools() -> None:
    for pid in orc.PHASE_IDS:
        text = (REPO / ".github" / "agents" / f"{pid}.agent.md").read_text(encoding="utf-8")
        assert ("atlassian/*" in text) == (pid == "requirements")
        assert ("github/*" in text) == (pid == "pr")
 
 
def test_mcp_config_contains_no_secret() -> None:
    config = json.loads((REPO / ".vscode" / "mcp.json").read_text(encoding="utf-8"))
    assert {"atlassian", "github"} <= set(config["servers"])
    assert orc.find_secrets(json.dumps(config)) == []
    assert "headers" not in config["servers"]["github"]  # sign-in is OAuth in VS Code; no token in the file
 
 
# ------------------------------------------------------------------------------ init and ordering
def test_init_creates_state_and_audit_and_cannot_repeat(root: Path) -> None:
    o = make(root)
    o.init("tester")
    assert (root / "sdlc" / "state.json").stat().st_size > 0
    assert o.audit.read()[0]["event"] == "state.initialized"
    with pytest.raises(StateError, match="already initialized"):
        o.init("tester")
 
 
def test_uninitialized_state_is_reported_not_guessed(root: Path) -> None:
    (root / "sdlc" / "state.json").write_text("", encoding="utf-8")
    with pytest.raises(StateError, match="empty"):
        make(root).current()
 
 
def test_phases_cannot_start_out_of_order(orch: Orchestrator) -> None:
    with pytest.raises(TransitionError, match="requires approved prerequisite"):
        orch.start("architecture")
    orch.start("requirements")
    with pytest.raises(TransitionError, match="requires approved prerequisite"):
        orch.start("architecture")
 
 
def test_cannot_start_a_phase_twice(orch: Orchestrator) -> None:
    orch.start("requirements")
    with pytest.raises(TransitionError, match="not 'not_started'"):
        orch.start("requirements")
 
 
def test_current_points_at_the_next_action(orch: Orchestrator) -> None:
    assert orch.current()["can_start"] == "requirements"
    orch.start("requirements")
    assert "submit requirements" in orch.current()["next_action"]
 
 
# ------------------------------------------------------------------------------ artifact validation
def test_submit_requires_the_output_file(orch: Orchestrator) -> None:
    orch.start("requirements")
    with pytest.raises(ValidationFailed) as err:
        orch.submit("requirements")
    assert any(i.code == "missing-output" for i in err.value.issues)
 
 
def test_submit_rejects_missing_sections_and_placeholders_and_secrets(root: Path, orch: Orchestrator) -> None:
    advance(orch, root, "architecture")
    orch.start("architecture")
    path = write_artifact(root, orch, "architecture")
    good = path.read_text(encoding="utf-8")
 
    path.write_text(good.replace("## Security Considerations", "## Something Else"), encoding="utf-8")
    with pytest.raises(ValidationFailed) as err:
        orch.submit("architecture")
    assert any(i.code == "missing-section" for i in err.value.issues)
 
    path.write_text(good + "\nTODO write this later\n", encoding="utf-8")
    with pytest.raises(ValidationFailed) as err:
        orch.submit("architecture")
    assert any(i.code == "placeholder" for i in err.value.issues)
 
    path.write_text(good + "\ntoken = 'abcdefghijklmnop1234'\n", encoding="utf-8")
    with pytest.raises(ValidationFailed) as err:
        orch.submit("architecture")
    assert any(i.code == "secret-detected" for i in err.value.issues)
 
    path.write_text(good, encoding="utf-8")
    assert orch.submit("architecture") == "awaiting_approval"
 
 
def test_lowercase_todo_is_allowed_in_artifacts(root: Path, orch: Orchestrator) -> None:
    advance(orch, root, "architecture")
    orch.start("architecture")
    write_artifact(root, orch, "architecture", body="The todo list stores todo items in todo.json for each user. " * 2)
    assert orch.submit("architecture") == "awaiting_approval"
 
 
def test_review_verdict_changes_requested_blocks_submission(root: Path, orch: Orchestrator) -> None:
    advance(orch, root, "design-review")
    orch.start("design-review")
    write_artifact(root, orch, "design-review", "Verdict: CHANGES_REQUESTED")
    with pytest.raises(ValidationFailed) as err:
        orch.submit("design-review")
    assert any(i.code == "pattern-not-met" for i in err.value.issues)
 
 
# ------------------------------------------------------------------------------ Confluence evidence
def test_requirements_need_real_confluence_evidence(root: Path, orch: Orchestrator) -> None:
    stale_seq = mcp_confluence(orch)  # recorded before the phase starts
    orch.start("requirements")
    path = write_artifact(root, orch, "requirements", f"Confluence-URL: {URL}\nEvidence-ID: {stale_seq}")
    with pytest.raises(ValidationFailed, match="failed validation") as err:
        orch.submit("requirements")
    assert "predates" in str(err.value.issues)
 
    write_artifact(root, orch, "requirements", f"Confluence-URL: {URL}\nEvidence-ID: 9999")
    with pytest.raises(ValidationFailed) as err:
        orch.submit("requirements")
    assert "not a recorded Confluence MCP call" in str(err.value.issues)
 
    seq = mcp_confluence(orch, urls=["https://example.atlassian.net/wiki/spaces/OTHER/pages/1"])
    write_artifact(root, orch, "requirements", f"Confluence-URL: {URL}\nEvidence-ID: {seq}")
    with pytest.raises(ValidationFailed) as err:
        orch.submit("requirements")
    assert "was not returned by any cited MCP call" in str(err.value.issues)
 
    seq = mcp_confluence(orch, chars=20)
    write_artifact(root, orch, "requirements", f"Confluence-URL: {URL}\nEvidence-ID: {seq}")
    with pytest.raises(ValidationFailed) as err:
        orch.submit("requirements")
    assert "no usable content" in str(err.value.issues)
 
    seq = mcp_confluence(orch)
    write_artifact(root, orch, "requirements", f"Confluence-URL: {URL}\nEvidence-ID: {seq}")
    assert orch.submit("requirements") == "awaiting_approval"
    assert path.exists()
 
 
def test_an_evidence_id_that_is_not_an_mcp_call_is_rejected(root: Path, orch: Orchestrator) -> None:
    orch.start("requirements")
    write_artifact(root, orch, "requirements", f"Confluence-URL: {URL}\nEvidence-ID: 1")  # seq 1 is state.initialized
    with pytest.raises(ValidationFailed):
        orch.submit("requirements")
 
 
# ------------------------------------------------------------------------------ approval gate
def test_approval_needs_a_human_confirmation(root: Path, orch: Orchestrator) -> None:
    orch.start("requirements")
    write_artifact(root, orch, "requirements", extra_for(orch, root, "requirements"))
    orch.submit("requirements")
 
    with pytest.raises(ApprovalError, match="interactive human confirmation"):
        make(root, confirm=None).approve("requirements", "alice")
    assert phase_status(orch, "requirements") == "awaiting_approval"
 
    with pytest.raises(ApprovalError, match="not confirmed"):
        make(root, confirm=lambda phrase: False).approve("requirements", "alice")
    assert phase_status(orch, "requirements") == "awaiting_approval"
 
    seen: list[str] = []
    make(root, confirm=lambda phrase: seen.append(phrase) or True).approve("requirements", "alice", "looks good")
    assert seen == ["APPROVE requirements"]
    state = orch.state.load()[0]["phases"]["requirements"]
    assert state["status"] == "approved"
    assert state["approval"]["method"] == "human-confirmation"
    assert state["approval"]["approved_hashes"] == state["artifact_hashes"]
 
 
@pytest.mark.parametrize("name", ["copilot", "gpt-4", "claude", "review-agent", "requirements", "orchestrator", "ci-bot", "x"])
def test_automated_or_malformed_approvers_are_refused(root: Path, orch: Orchestrator, name: str) -> None:
    orch.start("requirements")
    write_artifact(root, orch, "requirements", extra_for(orch, root, "requirements"))
    orch.submit("requirements")
    with pytest.raises(ApprovalError):
        orch.approve("requirements", name)
    assert phase_status(orch, "requirements") == "awaiting_approval"
 
 
def test_cli_approve_is_refused_without_a_terminal(root: Path, orch: Orchestrator, capsys: pytest.CaptureFixture[str]) -> None:
    orch.start("requirements")
    write_artifact(root, orch, "requirements", extra_for(orch, root, "requirements"))
    orch.submit("requirements")
    rc = orc.main(["--root", str(root), "approve", "requirements", "--approver", "alice"])
    assert rc == ExitCode.APPROVAL_DENIED
    assert "interactive terminal" in capsys.readouterr().err
    assert phase_status(orch, "requirements") == "awaiting_approval"
 
 
def test_automatic_phases_cannot_be_approved_by_hand(root: Path, orch: Orchestrator) -> None:
    # No phase is automatic any more: implementation (formerly automatic) now waits for a human, and only an
    # interactive human confirmation records the approval.
    assert all(p.approval_required for p in orch.workflow.phases)
    advance(orch, root, "implementation")
    orch.start("implementation")
    write_artifact(root, orch, "implementation")
    assert orch.submit("implementation") == "awaiting_approval"
    assert orch.state.load()[0]["phases"]["implementation"]["approval"] is None
    with pytest.raises(ApprovalError, match="interactive human confirmation"):
        make(root, confirm=None).approve("implementation", "alice")
    with pytest.raises(ApprovalError):
        orch.approve("implementation", "copilot")
    assert phase_status(orch, "implementation") == "awaiting_approval"
    orch.approve("implementation", "alice")
    approval = orch.state.load()[0]["phases"]["implementation"]["approval"]
    assert approval["method"] == "human-confirmation" and approval["approver"] == "alice"


def test_every_phase_waits_for_human_approval_and_records_human_confirmation(root: Path, orch: Orchestrator) -> None:
    for pid in orch.workflow.ids:
        if pid == "pr":
            orch.start("pr")
            path = write_artifact(root, orch, "pr", PR_HEADER)
            orch.authorize_pr("acme/todo-app", "feature/todo", "main", "alice")
            seq = audit_event(orch, "mcp.call", kind="github_pr_created", tool="create_pull_request", is_error=False,
                              result_chars=300, urls=[PR_URL], target="acme/todo-app feature/todo main",
                              pr_body_digest=orc.pr_body_digest(path.read_text(encoding="utf-8")))
            path.write_text(path.read_text(encoding="utf-8") + f"\nPR-URL: {PR_URL}\nPR-Evidence-ID: {seq}\n", encoding="utf-8")
        else:
            orch.start(pid)
            write_artifact(root, orch, pid, extra_for(orch, root, pid))
        assert orch.submit(pid) == "awaiting_approval", pid
        assert phase_status(orch, pid) == "awaiting_approval"
        assert orch.state.load()[0]["phases"][pid]["approval"] is None
        orch.approve(pid, "alice")
        approval = orch.state.load()[0]["phases"][pid]["approval"]
        assert phase_status(orch, pid) == "approved"
        assert approval["method"] == "human-confirmation" and approval["approver"] == "alice", pid
    assert orch.validate().ok


@pytest.mark.parametrize("pid", ["implementation", "verify"])
def test_phases_cannot_be_configured_as_automatic(root: Path, pid: str) -> None:
    data = json.loads((root / "sdlc" / "phases.json").read_text(encoding="utf-8"))
    next(p for p in data["phases"] if p["id"] == pid)["approval_required"] = False
    with pytest.raises(orc.ConfigError, match="explicit human approval"):
        orc.parse_workflow(data)

 
def test_reject_returns_phase_to_in_progress(root: Path, orch: Orchestrator) -> None:
    orch.start("requirements")
    write_artifact(root, orch, "requirements", extra_for(orch, root, "requirements"))
    orch.submit("requirements")
    orch.reject("requirements", "needs more detail")
    assert phase_status(orch, "requirements") == "in_progress"
    with pytest.raises(TransitionError):
        orch.reject("requirements", "again")
 
 
# ------------------------------------------------------------------------------ drift, stale, reopen
def test_changed_artifact_cannot_be_approved_and_marks_phases_stale(root: Path, orch: Orchestrator) -> None:
    advance(orch, root, "architecture")
    orch.start("architecture")
    path = write_artifact(root, orch, "architecture")
    orch.submit("architecture")
    path.write_text(path.read_text(encoding="utf-8") + "\nA late edit.\n", encoding="utf-8")
 
    with pytest.raises(TransitionError, match="changed after submission"):
        orch.approve("architecture", "alice")
    checked, drifted, _ = orch.revalidate()
    assert "architecture" in checked and "architecture" in drifted
    assert phase_status(orch, "architecture") == "stale"
    report = orch.validate()
    assert not report.ok and any(i.code == "stale-phase" for i in report.issues)
    with pytest.raises(TransitionError, match="not 'not_started'"):
        orch.start("architecture")
 
 
def test_revalidate_without_drift_is_clean(root: Path, orch: Orchestrator) -> None:
    advance(orch, root, "architecture")
    _, drifted, issues = orch.revalidate()
    assert drifted == {} and issues == []
 
 
def test_reopen_archives_downstream_files_and_resets_phases(root: Path, orch: Orchestrator) -> None:
    advance(orch, root, "design-review")  # requirements and architecture approved
    arch = root / "artifacts" / "architecture.md"
    content = arch.read_bytes()
 
    with pytest.raises(ApprovalError):
        make(root, confirm=lambda p: False).reopen("requirements", "scope change")
    assert arch.exists() and phase_status(orch, "architecture") == "approved"
 
    archived = orch.reopen("requirements", "scope change")
    assert archived == ["artifacts/architecture.md"]
    assert not arch.exists()
    copies = list((root / "artifacts" / "_archive").rglob("architecture.md"))
    assert len(copies) == 1 and copies[0].read_bytes() == content
    assert phase_status(orch, "requirements") == "in_progress"
    assert phase_status(orch, "architecture") == "not_started"
    assert orch.validate().ok
 
 
def test_reopen_needs_a_reason_and_a_submitted_phase(orch: Orchestrator) -> None:
    with pytest.raises(TransitionError):
        orch.reopen("requirements", "")
    with pytest.raises(TransitionError, match="only submitted, approved, or stale"):
        orch.reopen("requirements", "why")
 
 
# ------------------------------------------------------------------------------ state and audit integrity
def tamper_state(root: Path, mutate: Callable[[dict], None], fix_checksum: bool = False) -> None:
    path = root / "sdlc" / "state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    mutate(state)
    if fix_checksum:
        state["checksum"] = orc.checksum_of(state)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
 
 
def test_hand_edited_state_is_detected(root: Path, orch: Orchestrator) -> None:
    tamper_state(root, lambda s: s["phases"]["requirements"].update(status="approved"))
    with pytest.raises(StateError, match="checksum mismatch"):
        orch.current()
 
 
def test_hand_edited_state_with_recomputed_checksum_is_detected_through_the_audit_log(root: Path, orch: Orchestrator) -> None:
    tamper_state(root, lambda s: s["phases"]["requirements"].update(status="approved"), fix_checksum=True)
    with pytest.raises(StateError, match="does not match the audit log"):
        orch.current()
 
 
def test_corrupted_state_is_reported_and_left_untouched(root: Path, orch: Orchestrator) -> None:
    path = root / "sdlc" / "state.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(StateError, match="corrupted"):
        orch.start("requirements")
    assert path.read_text(encoding="utf-8") == "{ not json"
 
 
def test_edited_audit_entry_is_detected(root: Path, orch: Orchestrator) -> None:
    orch.start("requirements")
    log = root / "sdlc" / "audit.log.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["actor"] = "someone-else"
    lines[0] = json.dumps(entry, sort_keys=True)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert orch.audit.verify()
    with pytest.raises(StateError, match="audit log integrity"):
        orch.current()
 
 
def test_deleted_audit_entry_is_detected(root: Path, orch: Orchestrator) -> None:
    orch.start("requirements")
    orch.audit.append("note", actor="guard")
    log = root / "sdlc" / "audit.log.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines()
    del lines[1]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert orch.audit.verify()
 
 
def test_audit_log_is_hash_chained(orch: Orchestrator) -> None:
    orch.start("requirements")
    entries = orch.audit.read()
    assert entries[0]["prev_hash"] == orc.GENESIS_HASH
    assert all(b["prev_hash"] == a["hash"] for a, b in zip(entries, entries[1:]))
    assert orch.audit.verify() == []
 
 
def test_interrupted_transition_is_detected_and_recovered(root: Path, orch: Orchestrator, monkeypatch: pytest.MonkeyPatch) -> None:
    def crash(path: Path, text: str) -> None:
        raise OSError("disk full")
 
    with monkeypatch.context() as patch:
        patch.setattr(orc, "atomic_write_text", crash)
        with pytest.raises(OSError):
            orch.start("requirements")
    assert phase_status(orch, "requirements") == "not_started"  # the state file never changed
    assert orch.state.load()[1] is True  # audit is one step ahead: interrupted, not tampered
    orch.start("requirements")
    assert "state.recovered" in [e["event"] for e in orch.audit.read()]
    assert phase_status(orch, "requirements") == "in_progress"
    assert orch.state.load()[1] is False
 
 
# ------------------------------------------------------------------------------ pipeline validation
def test_validate_flags_premature_and_unowned_artifacts(root: Path, orch: Orchestrator) -> None:
    assert orch.validate().ok
    (root / "artifacts" / "architecture.md").write_text("early", encoding="utf-8")
    (root / "artifacts" / "random.md").write_text("stray", encoding="utf-8")
    codes = {i.code for i in orch.validate().issues}
    assert {"premature-artifact", "unowned-artifact"} <= codes
 
 
def test_archive_directory_is_not_flagged(root: Path, orch: Orchestrator) -> None:
    (root / "artifacts" / "_archive" / "x").mkdir(parents=True)
    (root / "artifacts" / "_archive" / "x" / "old.md").write_text("old", encoding="utf-8")
    assert orch.validate().ok
 
 
# ------------------------------------------------------------------------------ verification evidence (real pytest run)
def write_tests(root: Path, passing: bool) -> None:
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_sample.py").write_text(f"def test_sample():\n    assert {passing}\n", encoding="utf-8")
 
 
def verification_text(root: Path, orch: Orchestrator, seq: int) -> None:
    write_artifact(root, orch, "verify", f"Verdict: PASS\nEvidence-ID: {seq}")
 
 
def test_run_checks_only_while_verify_is_in_progress(orch: Orchestrator) -> None:
    with pytest.raises(TransitionError, match="only available while the 'verify' phase"):
        orch.run_checks()
 
 
def test_verify_accepts_only_passing_unchanged_evidence(root: Path, orch: Orchestrator) -> None:
    advance(orch, root, "verify")
    orch.start("verify")
    write_tests(root, passing=False)
    failing = orch.run_checks()
    assert failing["exit_code"] != 0 and failing["failed"] == 1
    verification_text(root, orch, failing["seq"])
    with pytest.raises(ValidationFailed, match="failed validation") as err:
        orch.submit("verify")
    assert "no passing" in str(err.value.issues)
 
    write_tests(root, passing=True)
    passing = orch.run_checks()
    assert passing["exit_code"] == 0 and passing["passed"] == 1
    verification_text(root, orch, passing["seq"])
    (root / "todo").mkdir()
    (root / "todo" / "late.py").write_text("x = 1\n", encoding="utf-8")  # source changes after the run
    with pytest.raises(ValidationFailed) as err:
        orch.submit("verify")
    assert "source changed since the tests ran" in str(err.value.issues)
 
    (root / "todo" / "late.py").unlink()
    assert orch.submit("verify") == "awaiting_approval"
    assert phase_status(orch, "verify") == "awaiting_approval"
    orch.approve("verify", "alice")
    assert phase_status(orch, "verify") == "approved"
    assert orch.state.load()[0]["phases"]["verify"]["approval"]["method"] == "human-confirmation"
 
 
# ------------------------------------------------------------------------------ pull request authorization
def pr_args(**overrides: str) -> dict[str, str]:
    return {"owner": "acme", "repo": "todo-app", "head": "feature/todo", "base": "main", **overrides}
 
 
def start_pr(root: Path, orch: Orchestrator) -> Path:
    advance(orch, root, "pr")
    orch.start("pr")
    return write_artifact(root, orch, "pr", PR_HEADER)
 
 
def test_pr_creation_is_blocked_until_a_human_authorizes(root: Path, orch: Orchestrator) -> None:
    ok, reason = orch.pr_creation_check(pr_args())
    assert not ok and "'pr' phase is in progress" in reason
    start_pr(root, orch)
    ok, reason = orch.pr_creation_check(pr_args())
    assert not ok and "no human authorization" in reason
 
 
def test_authorize_pr_requires_confirmation_and_matching_pr_md(root: Path, orch: Orchestrator) -> None:
    start_pr(root, orch)
    with pytest.raises(ApprovalError):
        make(root, confirm=None).authorize_pr("acme/todo-app", "feature/todo", "main", "alice")
    with pytest.raises(TransitionError, match="do not match pr.md"):
        orch.authorize_pr("acme/other", "feature/todo", "main", "alice")
    with pytest.raises(TransitionError, match="feature branch"):
        orch.authorize_pr("acme/todo-app", "main", "develop", "alice")
    with pytest.raises(TransitionError, match="distinct"):
        orch.authorize_pr("acme/todo-app", "main", "main", "alice")
    with pytest.raises(ApprovalError):
        orch.authorize_pr("acme/todo-app", "feature/todo", "main", "copilot")
    assert orch.pr_creation_check(pr_args())[0] is False
 
 
def test_authorized_pr_is_exact_and_single_use(root: Path, orch: Orchestrator) -> None:
    path = start_pr(root, orch)
    orch.authorize_pr("acme/todo-app", "feature/todo", "main", "alice")
    assert orch.pr_creation_check(pr_args()) == (True, "")
    for wrong in (pr_args(repo="other"), pr_args(owner="evil"), pr_args(head="feature/other"), pr_args(base="release")):
        ok, reason = orch.pr_creation_check(wrong)
        assert not ok and "differ from the authorized" in reason
 
    original = path.read_text(encoding="utf-8")
    path.write_text(original.replace("## Title", "## Title\nA different title."), encoding="utf-8")
    ok, reason = orch.pr_creation_check(pr_args())
    assert not ok and "changed after authorization" in reason
    path.write_text(original, encoding="utf-8")
    assert orch.pr_creation_check(pr_args())[0]
 
    audit_event(orch, "mcp.call", kind="github_pr_created", tool="create_pull_request", is_error=True, result_chars=10, urls=[])
    assert orch.pr_creation_check(pr_args())[0]  # a failed attempt does not consume the authorization
    audit_event(orch, "mcp.call", kind="github_pr_created", tool="create_pull_request", is_error=False, result_chars=300, urls=[PR_URL])
    ok, reason = orch.pr_creation_check(pr_args())
    assert not ok and "already created" in reason
 
 
def test_pr_submit_requires_evidence_of_the_authorized_creation(root: Path, orch: Orchestrator) -> None:
    path = start_pr(root, orch)
    with pytest.raises(ValidationFailed) as err:
        orch.submit("pr")
    assert "no human authorization" in str(err.value.issues)
 
    orch.authorize_pr("acme/todo-app", "feature/todo", "main", "alice")
    path.write_text(path.read_text(encoding="utf-8") + f"\nPR-URL: {PR_URL}\nPR-Evidence-ID: 1\n", encoding="utf-8")
    with pytest.raises(ValidationFailed) as err:
        orch.submit("pr")
    assert "does not match a create_pull_request call" in str(err.value.issues)
 
    seq = audit_event(orch, "mcp.call", kind="github_pr_created", tool="create_pull_request", is_error=False,
                      result_chars=300, urls=[PR_URL], target="acme/todo-app feature/other main",
                      pr_body_digest=orc.pr_body_digest(path.read_text(encoding="utf-8")))
    path.write_text(path.read_text(encoding="utf-8").replace("PR-Evidence-ID: 1", f"PR-Evidence-ID: {seq}"), encoding="utf-8")
    with pytest.raises(ValidationFailed):  # created for a different head branch
        orch.submit("pr")
 
 
def test_full_pipeline_end_to_end(root: Path, orch: Orchestrator) -> None:
    advance(orch, root, "pr")
    run_pr(orch, root)
    assert orch.current()["complete"] is True
    assert orch.validate().ok, orch.validate().issues
    rows, _ = orch.status()
    assert [r.status for r in rows] == ["approved"] * 8
    assert orch.audit.verify() == []
    assert orc.main(["--root", str(root), "validate"]) == ExitCode.OK
 
 
# ------------------------------------------------------------------------------ CLI
def test_cli_status_describe_audit_and_errors(root: Path, orch: Orchestrator, capsys: pytest.CaptureFixture[str]) -> None:
    assert orc.main(["--root", str(root), "status"]) == 0
    assert "requirements" in capsys.readouterr().out
    assert orc.main(["--root", str(root), "describe", "pr"]) == 0
    assert "Pull Request" in capsys.readouterr().out
    assert orc.main(["--root", str(root), "audit"]) == 0
    assert "INTACT" in capsys.readouterr().out
    assert orc.main(["--root", str(root), "start", "architecture"]) == ExitCode.TRANSITION_DENIED
    assert "requires approved prerequisite" in capsys.readouterr().err
    assert orc.main(["--root", str(root), "--json", "current"]) == 0
    assert json.loads(capsys.readouterr().out)["can_start"] == "requirements"
    assert "command.error" in [e["event"] for e in orch.audit.read()]
 
 
def test_cli_start_and_submit_roundtrip(root: Path, orch: Orchestrator, capsys: pytest.CaptureFixture[str]) -> None:
    assert orc.main(["--root", str(root), "start", "requirements"]) == 0
    assert orc.main(["--root", str(root), "submit", "requirements"]) == ExitCode.VALIDATION_FAILED
    assert "missing-output" in capsys.readouterr().err
 
 
# ------------------------------------------------------------------------------ helpers
@pytest.mark.parametrize("pattern,path,expected", [
    ("todo/**", "todo/app.py", True), ("todo/**", "todo/sub/x.py", True), ("todo/**", "todox/a.py", False),
    ("sdlc/**", "sdlc/state.json", True), ("tests/test_todo.py", "tests/test_todo.py", True),
    ("tests/test_todo.py", "tests/test_guard.py", False), ("*.md", "README.md", True), ("*.md", "docs/a.md", False),
    ("**/*.py", "a/b/c.py", True), ("orchestrator.py", "orchestrator.py", True),
])
def test_glob_match(pattern: str, path: str, expected: bool) -> None:
    assert orc.glob_match(pattern, path) is expected
 
 
def test_safe_relative_rejects_traversal_and_absolute() -> None:
    assert orc.safe_relative("./a//b.md") == "a/b.md"
    for bad in ("../x", "a/../../x", "/etc/passwd", "C:\\x", ""):
        with pytest.raises(ValueError):
            orc.safe_relative(bad)
 
 
def test_to_repo_relative_handles_symlink_escape(root: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    outside = tmp_path_factory.mktemp("outside")
    (root / "link").symlink_to(outside)
    assert orc.to_repo_relative(root, "link/secret.txt") is None
    assert orc.to_repo_relative(root, "/etc/passwd") is None
    assert orc.to_repo_relative(root, "a/b.txt") == "a/b.txt"
    assert orc.to_repo_relative(root, str(root / "a" / ".." / "c.txt")) == "c.txt"
 
 
def test_secret_and_placeholder_detection() -> None:
    assert "github-token" in orc.find_secrets("x ghp_" + "a" * 36)
    assert "aws-access-key" in orc.find_secrets("AKIA" + "A" * 16)
    assert orc.find_secrets("a normal sentence about tokens") == []
    assert orc.find_placeholders("TODO fix, TBD, FIXME and XXX") == ["FIXME", "TBD", "TODO", "XXX"]
    assert orc.find_placeholders("the todo app") == []
 
 
def test_source_digest_changes_with_content(root: Path) -> None:
    (root / "todo").mkdir()
    before = orc.source_digest(root, ["todo/**"])
    (root / "todo" / "a.py").write_text("x", encoding="utf-8")
    after = orc.source_digest(root, ["todo/**"])
    (root / "todo" / "a.py").write_text("y", encoding="utf-8")
    assert len({before, after, orc.source_digest(root, ["todo/**"])}) == 3
 