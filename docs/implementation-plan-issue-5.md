# Implementation Plan: Issue #5 — Let Claude Code Use Academic Agent

## Objective

Let Claude Code run Academic Agent on subtasks so it can exercise the agent
heavily, and open GitHub issues for the defects it finds.

## Design decisions

- **Integration surface: the existing CLI plus a `--json` mode.** No MCP
  server and no new dependency. Claude Code calls `academic` through its Bash
  tool and parses one JSON document from stdout.
- **A Claude Code skill drives the testing**: `.claude/skills/test-academic-agent/SKILL.md`
  in this repo, describing how to run scenarios, interpret results and report
  failures.
- **Findings are filed directly**: the skill runs `gh issue create` for each
  confirmed, de-duplicated finding, without asking.

## Current gaps in non-interactive use

Found in the code (`__main__.py`, `loop.py`, `ui.py`):

1. Without a TTY only `--auto-approve` is allowed. That is fine, but:
2. A `question` reply calls `ui.read_line`, gets EOF, raises `ui.Quit`, and
   exits with **code 0** ("Session kept"). The caller cannot tell this apart
   from success.
3. A `done` reply asks "Accept and finish?", also gets EOF, exits 0, and the
   session is **not** cleared.
4. A dangerous command under `--auto-approve` still prompts and ends the same
   way, with no information about what was blocked.
5. API errors and the step limit go through `_confirm`, which has the same
   ambiguity.
6. All output is human-oriented text mixed with ANSI (when TTY) on stdout.

## Phase 1: `--json` non-interactive mode

1. New flag `--json` (only valid together with `--auto-approve`, or implying
   non-interactive mode). In this mode:
   - All human UI output goes to **stderr** (spinner disabled). Stdout gets
     exactly one JSON object at exit.
   - No call to `input()`. Every point that would prompt ends the run with a
     structured result instead.
2. Result schema (versioned):

   ```json
   {"version": 1,
    "status": "done" | "question" | "blocked" | "error" | "step_limit",
    "message": "...",            // done summary / question text / error
    "blocked_command": "...",    // for status=blocked, with "reason"
    "changed_files": [...],
    "run_log": [...], "timings": [...],   // timings from issue #4 if present
    "tokens_in": 0, "tokens_out": 0, "steps": 0,
    "session": "<cwd-hash>"}
   ```
3. Exit codes: `0` done, `3` question (answer with `--resume "answer"`),
   `4` blocked dangerous command, `5` step limit, `1` API/config error,
   `2` usage error. Document them in `docs/api-reference.md`.
4. `done` in JSON mode auto-accepts: the session is cleared and the run
   exits 0. Other statuses keep the session so `--resume` continues it.
5. To approve a blocked command: `--resume --approve-blocked`. It is accepted
   only for the exact command recorded in the session, so the caller cannot
   approve arbitrary commands.
6. Implementation: an `interactive=False` / `json_mode` flag on `Agent`.
   `_question`, `_done`, `_confirm`, `_ask_approval` and the API-error path
   raise a small `StopForCaller(status, …)` exception, which `run()` turns
   into the JSON result.

## Phase 2: Claude Code skill

`.claude/skills/test-academic-agent/SKILL.md` contains:

1. Prerequisites: configured `~/.config/academic-agent/env`, `gh` auth.
2. How to run a scenario: create a throwaway git repo under a temp dir with
   fixture files, run `academic --auto-approve --json "<task>"` with a Bash
   timeout, and loop on `question`/`blocked` with `--resume` until a terminal
   status.
3. A scenario catalogue covering: read-only questions, small edits,
   multi-file refactors, failing tests to fix, a task that should trigger a
   question, a task that tempts a dangerous command, large files and long
   outputs, Unicode, resume after interruption, and memory (`remember`, once
   issue #3 lands).
4. Checks for each run: status and exit code consistency, the expected file
   changes (diff the temp repo), no edits outside the repo, step count and
   timings within reason, and a valid JSON result.
5. Reporting: for each confirmed failure, first search existing issues
   (`gh issue list --search`) to avoid duplicates, then
   `gh issue create --label agent-found` with title, scenario, exact command,
   expected vs. actual, and the JSON result (the skill must not include
   credentials; the agent's output is already redacted).
6. Limits: at most N scenarios per run and no recursion. The agent under
   test must not call Claude Code or `academic` itself (the skill checks
   `run_log`).

## Phase 3: Offline tests (CI)

- `test_main.py`/`test_loop.py` with a fake `ApiClient` returning scripted
  replies: done → exit 0 and JSON on stdout only; question → exit 3, and
  resume with an answer continues; dangerous command → exit 4, and
  `--approve-blocked` runs exactly that command; step limit → 5; API error
  → 1.
- Check that stdout contains exactly one parseable JSON object and that
  `input()` is never called in JSON mode.
- Check that existing interactive behaviour is unchanged.

No Claude Code binary, credentials or network are needed in CI. The skill
itself is tested manually.

## Documentation

`docs/usage.md` (non-interactive JSON mode, exit codes, resume loop),
`docs/api-reference.md` (result schema), `docs/development.md` (how to run
the Claude Code testing skill), and `docs/security.md` (`--json` does not
widen approvals; blocked commands need an explicit, exact re-approval).

## Acceptance criteria

- `academic --auto-approve --json "task"` never blocks on stdin and always
  prints one JSON result with a status-specific exit code.
- Questions and dangerous commands come back to the caller and can be
  answered or approved via `--resume`.
- The Claude Code skill runs a scenario catalogue against temp repos and opens
  de-duplicated GitHub issues for failures.
- Offline tests cover every status and exit code, and interactive mode is
  unchanged.
