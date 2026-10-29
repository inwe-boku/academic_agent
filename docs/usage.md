# Usage

## Command line

```text
academic [--accept-edits | --auto-approve] [--max-steps N] [--resume] [task ...]
academic --auto-approve --json [--resume [--approve-blocked]] [task ...]
academic --list-models | --sessions | --clear
```

| Argument | Meaning |
| --- | --- |
| `task ...` | The task in natural language. Quoting is optional but recommended. Required unless `--resume` is used. With `--resume` it is added as your next message. |
| `--accept-edits` | Apply file changes without asking. Shell commands still ask. |
| `--auto-approve` | Apply file changes and run commands without asking. Commands flagged as dangerous **still ask**. See [Security](security.md). |
| `--max-steps N` | Ask before continuing after N turns (default and maximum: 100). |
| `--resume` | Continue the last session of the current directory. See [Resuming a session](#resuming-a-session). |
| `--json` | Non-interactive run for programs: see [Running from other programs](#running-from-other-programs). Needs `--auto-approve`. |
| `--approve-blocked` | With `--resume`: approve the dangerous command that stopped the last `--json` run, exactly that command, once. |
| `--list-models` | Print the models available to your API client and exit. |
| `--sessions` | List all saved sessions and exit. |
| `--clear` | Delete the saved session of the current directory and exit. |

The agent works in the **current working directory** (the *project root*). Always
`cd` into the project first. The model can only read and change files inside it.

```bash
cd ~/projects/my-project
academic "Add a unit test for parse_date and run the test suite"
```

Pick a model for a single run without editing the config:

```bash
ACADEMIC_AI_MODEL=claude-opus-4-8 academic "Review setup.py for packaging mistakes"
```

stdin must be a terminal unless you pass `--auto-approve`; otherwise the agent
stops with an error instead of hanging on a prompt.

## Running from other programs

`--json` is for callers such as scripts or Claude Code. The agent never reads
stdin. All human-readable output goes to stderr, and stdout gets exactly one
JSON object when the run ends. Wherever an interactive run would ask you
something, a `--json` run stops and reports it:

| `status` | Exit code | Meaning | Continue with |
| --- | --- | --- | --- |
| `done` | 0 | Task finished; the session is deleted | — |
| `error` | 1 | API/config error, repeated invalid replies, or `edit_file` failed 3 times in a row on one file; session kept | `--resume "instruction"` |
| `question` | 3 | The model asks something (`message`) | `--resume "answer"` |
| `blocked` | 4 | A dangerous command needs approval (`blocked_command`, `reason`) | `--resume --approve-blocked`, or `--resume "do X instead"` |
| `step_limit` | 5 | `--max-steps` reached | `--resume` |
| `interrupted` | 130 | Ctrl-C / SIGINT | `--resume` |

Usage errors (exit 2) also print a JSON object with `status: "error"`.

```bash
academic --auto-approve --json "Delete build/ and rebuild" > result.json
# {"version": 1, "status": "blocked", "blocked_command": "rm -rf build", ...}
academic --auto-approve --json --resume --approve-blocked
```

`--approve-blocked` approves only the exact command string that was blocked,
and only once. Any other dangerous command is blocked again. The result
also contains `changed_files`, `run_log`, `steps`, `tokens_in`, `tokens_out`,
`timings` and `session_kept`; see the [API notes](api-reference.md#json-result-of-academic-json).

Commands that the agent runs get `ACADEMIC_AGENT_NESTED=1`, and `academic`
refuses to start when that variable is set, so the agent cannot start itself
recursively.

The Claude Code skill in `.claude/skills/test-academic-agent/` uses this mode
to stress-test the agent; see [Development](development.md#testing-with-claude-code).

## What a session looks like

```text
tokens 3,120 in / 180 out · session 3,120 in / 180 out · ~$0.0057
  Read the parser, then fix the off-by-one error.
[1/2] read_file src/parse.py
  ✓ OK
[2/2] edit_file src/parse.py
--- a/src/parse.py
+++ b/src/parse.py
@@ -10,3 +10,3 @@
-    return items[1:]
+    return items[0:]
Approve? [y]es / [n]o / [a]lways edit_file / or type a comment to reject: y
  ✓ OK
```

Each turn is one API request. The model answers with one of three replies:

| Reply | What happens |
| --- | --- |
| `actions` | One or more tool calls, run in order. File reads happen without asking; changes and commands ask according to the [approval rules](#approval). The batch stops at the first failure or rejection. |
| `question` | The question is shown and your answer is sent back. An empty answer stops the agent (the session is kept). |
| `done` | The final screen is shown: summary, files changed, commands run with exit codes, token and cost totals. Answer `y` to finish, or type a follow-up instruction. |

A dim status line after each turn shows tokens and the estimated cost.

### Tools

| Tool | Effect | Tier |
| --- | --- | --- |
| `read_file` | Numbered lines (200 per call, paging with `offset`/`limit`) | read |
| `list_dir` | Directory tree, honours `.gitignore` | read |
| `search` | Regex search (ripgrep if installed) | read |
| `edit_file` | Exact string replacement; shows a diff | write |
| `write_file` | Create a file, or overwrite one read in this session | write |
| `move_file` | Rename a file within the project | write |
| `delete_file` | Delete one file | write |
| `run` | Shell command in the project root (default 120 s, max 600 s) | exec |
| `remember` | Save a project fact to the [project memory](#project-memory) | memory (never asks) |

`edit_file` and `write_file` refuse to change a file that the model has not read
in this session or that changed on disk since it was read.

### Approval

| Tier | Default | `--accept-edits` | `--auto-approve` |
| --- | --- | --- | --- |
| read | auto | auto | auto |
| write | ask (with diff) | auto | auto |
| exec | ask | ask | auto |
| exec, flagged dangerous | ask | ask | **ask** |

At the prompt:

- `y` runs the action, `n` or Enter rejects it.
- `a` approves this tool for the rest of the session (not offered for
  dangerous commands).
- Anything else rejects the action and sends your text to the model as feedback.

### Slash commands

These work at every prompt (approval, question, final screen):

| Command | Effect |
| --- | --- |
| `/diff` | `git diff` of the files the agent changed |
| `/undo` | Restore changed files from the start commit and delete files the agent created, after confirming the list |
| `/cost` | Token and cost totals of the session |
| `/quit` | Stop; the session is kept for `--resume` |

`/diff` and `/undo` need a git repository. See [Undo](#undo-with-git).

### Limits

- **Steps:** after 100 turns (or `--max-steps`) the agent asks whether to
  continue for another round.
- **Output:** each tool result is capped at 200 lines or 20,000 characters; head
  and tail are kept with a marker such as `[... 4 120 lines omitted ...]`.
- **History:** when the conversation reaches 70 % of the model's context window,
  older turns are replaced by a model-written summary (shown to you). If that
  call fails, old tool results are replaced by one-line stubs.
- **Ctrl+C** while a command runs kills it and returns to the prompt. Ctrl+C
  elsewhere stops the agent and keeps the session.

## Undo with git

At start the agent records the current commit and which files already had
uncommitted changes.

- `/undo` restores the files the agent touched from that commit (working tree
  only, the index is not changed) and deletes files it created. Files that
  already had changes at start cannot be restored and are listed as such.
- The agent may commit, push and open pull requests (`git commit`, `git push`,
  `gh pr create`) when the task or `AGENTS.md` asks for it. Commands that
  discard work or rewrite history (`git reset --hard`, `git clean`,
  `git checkout --`, `git restore`, `git stash`, `git rebase`, force pushes) are
  flagged as dangerous.
- `/undo` only resets files in the working tree. It does **not** undo commits
  or pushes; after it, the restored state shows up as uncommitted changes.
- Changes made by shell commands (`run`) are **not** tracked; use `git diff` for
  a full view.
- Outside a git repository a warning is printed at start, and `/undo` and
  `/diff` are unavailable. With `--accept-edits` or `--auto-approve` you are
  asked once to confirm the mode.

## Resuming a session

Failed API requests are retried automatically (connection errors, timeouts,
HTTP 429 and 5xx) up to 4 times, waiting 2, 5, 15 and 30 seconds, or as long as
the server's `Retry-After` header says. If all retries fail you can retry right
away or stop:

```text
Progress is saved. Continue later with: academic --resume
```

Run `academic --resume` in the **same directory** to continue where it stopped.
Actions that already ran are not repeated. `academic --resume "also update the
README"` adds your text as the next message.

### Where the session is stored

Before every API call the conversation is written to

```text
${XDG_STATE_HOME:-~/.local/state}/academic-agent/<hash-of-directory>.json
```

- One file per working directory, overwritten atomically at every step. The
  directory has mode `700`, the file `600`.
- Content: task, messages, touched files, start commit, token totals and the
  list of commands run.
- The file is deleted only when you accept the final `done` screen. Stopped or
  failed sessions stay on disk.
- Known secret patterns (bearer tokens, `sk-...` keys, private keys, values of
  secret environment variables) are redacted from tool results before they are
  stored or sent.

```bash
academic --sessions      # list saved sessions
academic --clear         # delete the session of the current directory
```

## Writing good tasks

- Be specific about the outcome: *"write only the number to count.txt"* beats
  *"count the lines"*.
- Ask the model to inspect before changing: *"Look at the failing test, explain
  the cause, then fix it."*
- Name the commands you want used: *"Run `pytest tests/test_io.py` to verify."*
- Checks and cleanup are not run automatically. Ask for them, or put them in
  `AGENTS.md`.
- For a git workflow, say so explicitly or put it in `AGENTS.md`, for example:
  *"Work on a new branch, commit, push and open a pull request with gh."*
- To only ask a question, say so: *"Do not modify anything. Explain how the
  configuration is loaded."*

## Project instructions with `AGENTS.md`

The agent reads every `AGENTS.md` from the filesystem root down to the current
directory and includes the contents in the first message. Files closer to the
working directory come later and therefore take precedence:

```markdown
# AGENTS.md
- Use `pytest -q` to run tests; never run the integration tests.
- Python code is formatted with black (line length 100).
- Do not modify files under `data/`.
```

Because `AGENTS.md` content steers the model, review files from untrusted
repositories before running the agent there.

## Project memory

New sessions don't remember earlier ones. When the model learns something
durable about your project, such as where things are, how to run the tests,
conventions or pitfalls, it saves a one-line note with `remember`. This
never asks for approval, but every save is shown:

```
[1/1] remember Tests: run `pytest -q` from the repo root
  ✓ saved; added .academic/ to .gitignore
  📝 Remembered: Tests: run `pytest -q` from the repo root
```

The notes go to `.academic/MEMORY.md` in the project root. Every new session
gets them in its first message, after `AGENTS.md`, which still takes
precedence. In a git repository, the first save adds `.academic/` to
`.gitignore`, so notes stay on your machine.

The file is plain markdown: edit it, remove wrong notes, or delete it to
start over. Rules that should apply to everyone working on the project
belong in `AGENTS.md`, not in memory.

## What the model sees about your project

The first message contains the project root, your task, the `AGENTS.md` content,
the [project memory](#project-memory) and a file listing (3 levels, at most 300 entries, `.gitignore` honoured). The
model uses `list_dir`, `search` and `read_file` for more.

File tools never access `.git/`, `.env*`, `*.pem` or `id_*`, and they reject
paths outside the project root (including via symlinks or `..`). Files ignored by
`.gitignore` are left out of listings and searches but can be read when the
model names them explicitly.
