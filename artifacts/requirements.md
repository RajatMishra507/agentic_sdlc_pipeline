# Requirements

Source: Confluence page "Todo List User Story" (page id 393233), retrieved read-only through the Atlassian MCP server during this phase.

## Source User Stories

**US-1** (summary of the page statement): As a user, I want to manage a simple list of tasks from the command line so that I can keep track of what I need to do.

The page lists these acceptance criteria and notes, each treated as part of US-1:

- US-1.Create: a new task receives a unique id, has status `open`, and displays its id, title, and status. Repeating a no-op produces a clear message; an invalid or unknown id produces a clear error.
- US-1.View: tasks are shown in creation order. An empty list prints a clear empty-list message.
- US-1.Complete: an open task changes to `done`. Completing an already-done task prints a no-op message. An unknown id produces a clear error and no change.
- US-1.Reopen: a done task changes to `open`. Reopening an already-open task prints a no-op message. An unknown id produces a clear error.
- US-1.Delete: a task is removed. An unknown id produces a clear error.
- US-1.Notes: build a small Python command-line application. Task titles are free text.

## Functional Requirements

- FR-1 (US-1.Create): The application shall let the user add a task with a free-text title.
- FR-2 (US-1.Create): Each new task shall receive an id that is unique within the list and shall start with status `open`.
- FR-3 (US-1.Create): After adding a task, the application shall display the task's id, title, and status.
- FR-4 (US-1.View): The application shall list all tasks in creation order, showing id, title, and status for each.
- FR-5 (US-1.View): When the list is empty, the application shall print a clear empty-list message.
- FR-6 (US-1.Complete): The application shall change an `open` task to `done` when the user completes it by id.
- FR-7 (US-1.Complete): Completing a task that is already `done` shall print a no-op message and leave the task unchanged.
- FR-8 (US-1.Reopen): The application shall change a `done` task to `open` when the user reopens it by id.
- FR-9 (US-1.Reopen): Reopening a task that is already `open` shall print a no-op message and leave the task unchanged.
- FR-10 (US-1.Delete): The application shall remove a task when the user deletes it by id.
- FR-11 (US-1.Create, US-1.Complete, US-1.Reopen, US-1.Delete): For an invalid or unknown id, the application shall print a clear error message and shall not change any task.

## Non-Functional Requirements

- NFR-1 (US-1.Notes): The application shall be a small Python command-line application.
- NFR-2 (US-1.Notes): Task titles shall be accepted as free text without restriction on content beyond what the command line can carry.
- NFR-3 (US-1): Every message (no-op, empty list, error) shall be clear and understandable to a user without reading the source code.
- NFR-4 (US-1.Create): Task ids shall stay unique for the lifetime of the list, including after deletions.

## Acceptance Criteria

- AC-1 (FR-1, FR-2, FR-3): Given an empty list, when the user adds a task titled "Buy milk", then a task with a new unique id and status `open` is created and its id, title, and status are displayed.
- AC-2 (FR-2, NFR-4): Given a list where the most recently added task was deleted, when the user adds another task, then the new task's id differs from the id of every task that exists in the list.
- AC-3 (FR-4): Given tasks A, B, and C added in that order, when the user views the list, then they are shown in the order A, B, C with id, title, and status.
- AC-4 (FR-5): Given an empty list, when the user views the list, then a clear empty-list message is printed.
- AC-5 (FR-6): Given an `open` task, when the user completes it by id, then its status becomes `done`.
- AC-6 (FR-7): Given a `done` task, when the user completes it by id, then a no-op message is printed and the task stays `done`.
- AC-7 (FR-8): Given a `done` task, when the user reopens it by id, then its status becomes `open`.
- AC-8 (FR-9): Given an `open` task, when the user reopens it by id, then a no-op message is printed and the task stays `open`.
- AC-9 (FR-10): Given an existing task, when the user deletes it by id, then it no longer appears when the list is viewed.
- AC-10 (FR-11): Given a list without id 999, when the user completes, reopens, or deletes id 999, then a clear error is printed and no task changes.
- AC-11 (FR-11): Given an id that is not a valid id (for example "abc"), when the user runs any command that takes an id, then a clear error is printed and no task changes.
- AC-12 (NFR-1): Given the finished application, when it is run from the command line with Python, then all commands above are available without a graphical interface.
- AC-13 (NFR-2): Given a title containing spaces, punctuation, and non-ASCII characters, when the user adds the task, then the title is stored and displayed exactly as entered.

## Assumptions and Open Questions

- Assumption: the page's statement "Repeating a no-op produces a clear message" under Create is read as a general rule that a no-op action prints a clear message; it is covered concretely by FR-7 and FR-9.
- Assumption: "invalid id" means an id that is not a whole number identifying a task; "unknown id" means a valid id that matches no task.
- Open question: should tasks persist between runs of the program, or is an in-memory list per run acceptable? The page does not say.
- Open question: is an empty title allowed? The page says titles are free text but does not address the empty case.
- Open question: should an invalid id be reported differently from an unknown id, or with one shared message? The page only requires a clear error for both.
- Open question: what exact command names and output wording should be used? The page leaves this to the implementation.

## Evidence

Confluence-URL: https://rbitestuserrj.atlassian.net/wiki/spaces/~71202025eaf9215838446398153749e55e74f1/pages/393233/Todo+List+User+Story
Evidence-ID: 55

The page was fetched through the Atlassian MCP server (`getConfluencePage`, page id 393233) after this phase was reopened and restarted, and the stories above come from that result. Audit entry 55 is the `mcp.call` record the guard hook wrote for that fetch: kind `confluence`, no error, 1964 characters returned, and the page URL present in the result. Earlier entries (10 and 15) belong to a previous run of this phase and are not cited. The page content matches the earlier run, so the stories, requirements and acceptance criteria are unchanged.
