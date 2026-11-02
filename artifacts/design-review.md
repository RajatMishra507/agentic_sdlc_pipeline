# Design Review

## Scope Reviewed

Reviewed `artifacts/architecture.md` (approved) against `artifacts/requirements.md` (approved): functional requirements FR-1 to FR-11, non-functional requirements NFR-1 to NFR-4, acceptance criteria AC-1 to AC-13, and the four open questions the requirements left unresolved.

Checks performed:

- Requirement coverage: every FR and NFR is mapped in the Traceability table, and each mapping names a component and a mechanism.
- Interface consistency: function signatures, CLI commands, exit codes, message patterns and the storage format were compared with each other and with the `todo/` modules already in the workspace.
- Security considerations: each claim was checked for whether it is a real control or only a statement.
- One behavior claim was tested by running the existing CLI against a throwaway temporary file (see finding 1). No repository file was changed.

Overall: the design is coherent and small, and it covers all requirements. The findings below are refinements, not blockers.

## Findings

1. **Severity: medium. Component: CLI exit codes and error table (FR-11, AC-11, NFR-3).**
   The error table says an id that is not a whole number gives exit code 1 with `invalid id '<id>': ...`. That holds for `abc`, `0`, `1.5` and `-1`; each was run and returned exit 1 with the documented message. An id that begins with a dash and looks like an option, such as `-x`, does not. It returns exit 2 with `todo done: error: the following arguments are required: id`, which is misleading and not the documented message. The design documents the `--` workaround in help text but not this outcome.
   Recommended change: state this case in the error table and decide whether it is accepted. If it is accepted, the planned tests should record it as an explicit exception to AC-11. If not, the CLI should accept the id argument in a way that lets it reach `parse_id`.

2. **Severity: medium. Component: Display rules and NFR-2 / AC-13 ("stored and displayed exactly as entered").**
   The design escapes non-printable characters when printing, so a title containing a control character or newline is not displayed exactly as entered. This is a sound security decision, but it is a deviation from the literal wording of AC-13, and the Traceability row for NFR-2 only mentions "printable text displayed unchanged". The architecture also asks the approver to overrule D-3 but does not flag this display deviation as a decision.
   Recommended change: add a decision (for example D-9) that records the display escaping as an accepted narrowing of AC-13 and NFR-2, limited to non-printable characters. The tests should cover both printable non-ASCII text, which must be unchanged, and a control character, which must be escaped.

3. **Severity: medium. Component: D-3 (empty titles) and NFR-2.**
   Rejecting empty or whitespace-only titles narrows NFR-2 ("without restriction on content"). The design flags this for the approver, which is appropriate. The open question is therefore only resolved if the human confirms it at approval; the planning phase should treat D-3 as provisional until then.
   Recommended change: no change to the design. Record the approver's answer in the approval note, and keep a test for the empty-title error so that it is easy to reverse.

4. **Severity: low. Component: Security, "Storage location" and "Atomic, private writes".**
   The text says the program writes "only to that path and its parent directory". The implementation also creates missing parent directories (`mkdir(parents=True)`), which can create several levels. The design also does not say that an existing file's permissions are replaced by the owner-only mode of the new file.
   Recommended change: add one sentence on parent-directory creation and one on permission replacement, so the documented behavior matches what the code does.

5. **Severity: low. Component: D-5 (no locking).**
   The list is loaded when `TodoList` is constructed and saved later from that in-memory copy, so two overlapping invocations can lose an update. The design accepts this for a single-user tool and says so. It does not describe the effect on `next_id`: two processes that both loaded `next_id = 4` could each save a task with id 4, which would break the uniqueness guarantee in NFR-4 even though each file write is atomic.
   Recommended change: state this limit under NFR-4 in the traceability note (uniqueness holds for sequential use), so the guarantee is not overstated.

6. **Severity: low. Component: Requirements wording carried into the design (FR-11).**
   FR-11 lists the Create story among those that take an id, but `add` takes no id. The architecture quietly ignores it. The mapping is harmless, but the traceability row should say that Create has no id input, so a reader does not look for a missing behavior.
   Recommended change: add a note to the FR-11 traceability row.

7. **Severity: low. Component: Function signatures (`TodoList.list`).**
   A method named `list` inside `TodoList` shadows the built-in `list` within the class body. The return annotation `list[Item]` is safe only while annotations are not evaluated at definition time (`from __future__ import annotations`). The design relies on this without saying so.
   Recommended change: record the dependency on postponed annotations in the Components section, or rename the method.

8. **Severity: low. Component: NFR-3 (clear messages).**
   NFR-3 has no measure, and the design answers it with a message table. The exact message text is the only thing that makes it testable.
   Recommended change: have the plan pin the message patterns in the table as exact expected strings in the tests.

9. **Severity: low. Component: D-4 wording.**
   The decision says "one message style ... with different wording", while its alternative is "one shared message". The two read as nearly the same thing.
   Recommended change: reword D-4 to say the design uses two distinct messages, one for malformed ids and one for unknown ids.

## Risks

- **Existing code predates this design.** `todo/app.py` and `todo/cli.py` already exist in the workspace and match the architecture closely, left over from the cycle that was reopened. If planning and implementation assume the code is correct, they could skip behavior the design requires. The plan should include verifying the existing code against every FR and AC rather than treating it as done.
- **Open decisions need the human.** D-1, D-3, D-4 and D-6 answer questions the requirements left open. Once approved they become the contract; changing one later means reopening upstream phases.
- **Concurrent use.** Overlapping runs can lose an update or duplicate an id (finding 5). The risk is low for a single-user tool, but the guarantee should be worded carefully.
- **Terminal behavior.** Escaping covers non-printable characters, but not every character that terminals treat specially if the platform reports it as printable. The risk is low and the control is reasonable for the scope.

## Verdict

Verdict: APPROVED_WITH_CONDITIONS

Conditions for the planning phase: (a) cover the `-x`-style id outcome in the plan and tests (finding 1); (b) treat the display escaping as a recorded narrowing of AC-13 (finding 2); (c) treat D-3 as provisional until the human confirms it (finding 3); (d) include a task to verify the existing `todo/` code against all requirements (Risks). No finding requires reopening the architecture phase.
