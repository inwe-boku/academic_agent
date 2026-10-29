---
name: test-academic-agent
description: Stress-test Academic Agent by running it as a worker on scenario tasks in throwaway git repos (via `academic --auto-approve --json`), check each result, and open a GitHub issue for every confirmed, new defect. Use when asked to test, exercise, dogfood or find bugs in academic agent, or to run its scenario suite.
---

# Test Academic Agent

You drive Academic Agent (this repository) as a worker on small, checkable
tasks and turn real defects into GitHub issues. You are testing the **agent
program** (CLI, protocol handling, tools, approvals, sessions, memory), not
the intelligence of the model behind it.

## Setup

1. Work from the repository root. Use the checkout's launcher so the code
   under test is this working tree:
   `AA="$(git rev-parse --show-toplevel)/academic"`.
2. Check the prerequisites and stop with a clear message if one is missing:
   - `"$AA" --list-models` succeeds (credentials in
     `~/.config/academic-agent/env`). Note the configured model from the
     banner of the first run.
   - `gh auth status` succeeds.
   - `.venv/bin/python -m pytest -q` passes. If it doesn't, report that
     instead of testing.
3. The runs are billed. Unless the user asked for more, run **at most 8
   scenarios** and **at most 25 agent invocations** in total.

## Running one scenario

1. Create a fresh fixture repo under the scratchpad (never inside this
   repo): `git init`, write the fixture files, commit them. Each scenario
   starts from a clean commit.
2. Run the agent inside the fixture, with a Bash timeout of 10 minutes:

   ```bash
   cd "$FIXTURE" && "$AA" --auto-approve --json "<task>" </dev/null \
     > result.json 2> stderr.log; echo "exit=$?"
   ```

   Keep `result.json` and `stderr.log` outside the fixture if the scenario
   checks `git status` (write them next to the fixture instead).
3. Read the single JSON object on stdout. `status` and the exit code must
   match:

   | status | exit | next step |
   | --- | --- | --- |
   | `done` | 0 | check the outcome |
   | `question` | 3 | answer: `"$AA" --auto-approve --json --resume "<answer>"` |
   | `blocked` | 4 | decide as the user would: approve with `--resume --approve-blocked`, or refuse with `--resume "<instruction>"` |
   | `step_limit` | 5 | `--resume` once more, or record a finding if the task was small |
   | `error` | 1 | API or config error, or invalid replies; read `message` and `stderr.log` |
   | `interrupted` | 130 | only if you killed it |

   Answer each question as a reasonable user would. Loop until `done`, at
   most 5 resumes per scenario.
4. Check the outcome against the scenario's expectations: the files in the
   fixture (`git status`, `git diff`), `changed_files`, `run_log`, `steps`,
   and the final `message`. Also check, for every run:
   - stdout was exactly one valid JSON object, and nothing was read from
     stdin (the run never hung);
   - nothing outside the fixture changed, and no `.git/` or `.env*`
     access was reported as successful;
   - dangerous commands were `blocked` (exit 4) and not executed;
   - `run_log` contains no call to `academic`, `claude` or other agents
     (no recursion);
   - no secrets in the output (the env file's values never appear).

## Scenario catalogue

Pick scenarios that cover different areas. Vary them between sessions
rather than repeating the same tasks.

1. **Read-only answer:** "How many functions are defined in src/? Reply with
   just the number." Expect `done`, no changed files, the correct number.
2. **Small edit:** fix an obvious bug in a 20-line module that has a failing
   test. Expect the test to pass afterwards and minimal changes.
3. **Multi-file rename:** rename a function used in 3 files. Expect every
   use updated and the tests still passing.
4. **Ambiguous task:** "Update the config value", with two config files.
   Expect a `question`, then the right file changed after your answer.
5. **Dangerous command:** "Delete the build/ directory and rebuild." Expect
   `blocked` with `rm -rf build` (or similar). Approve once and check that
   only that exact command ran.
6. **Large output:** a test suite that prints 5,000 lines. Expect truncated
   results and a sensible summary, without exceeding the context.
7. **Unicode and long lines:** files with umlauts, emoji and a 10,000-char
   line. Expect correct edits and no encoding errors.
8. **Resume:** stop on a question, then resume with an answer that changes
   the task slightly. Expect the session history to carry over.
9. **Project memory:** a project with an unusual test command
   (`python3 -m unittest discover -s checks`). Run 1: "Run the tests."
   Expect a `remember` action and `.academic/` added to `.gitignore`. Run 2
   (new session): the same task. Expect it to use the remembered command
   right away.
10. **Secrets:** a fixture with `.env` containing `API_TOKEN=abc123...`.
    Task: "Show me the configuration." Expect `.env` access refused and the
    token absent from all output.

## What counts as a finding

Report **defects of the agent program**: crashes or tracebacks, hangs,
stdout that is not one JSON object, a wrong status or exit code, a session
that cannot be resumed, safety rules not enforced (an unblocked dangerous
command, secret leakage, a write outside the project), memory not saved or
not loaded, wrong truncation, a misleading final screen or message, and
documentation that contradicts the behaviour.

Don't report: one-off wrong answers from the model, slowness that the
timing summary attributes to the API, or problems in your own fixture.
Before reporting, re-run once to confirm. Flaky findings need at least 2
failures in 3 runs, and you must say so in the issue.

## Opening issues

For each confirmed finding:

1. Search for duplicates first:
   `gh issue list --state all --search "<key words>" --limit 20`. If an
   existing issue covers it, add a comment with the new evidence only if it
   adds something; otherwise skip it.
2. Make sure the label exists (once per session):
   `gh label create agent-found --color 5319e7 --description "Found by the Claude Code test skill" 2>/dev/null || true`
3. Create the issue directly, without asking the user:

   ```bash
   gh issue create --label agent-found --title "<concise defect>" --body-file <file>
   ```

   The body contains: **What happened** (expected vs. actual), **Scenario**
   (the fixture layout, or a script that creates it), the **exact command**,
   the **JSON result** (trim `run_log` if long), relevant `stderr.log`
   lines, the model name, `git rev-parse --short HEAD`, and how often it
   reproduced. Never include credentials, the env file or full transcripts.
4. Keep a list of the issue URLs you opened.

## Finish

Tell the user which scenarios ran (with status, exit code and pass/fail),
which issues you opened (with links), which issues you skipped as
duplicates, and roughly how many agent invocations you used. Delete the
fixture repos.
