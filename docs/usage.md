# Usage

## Command line

```text
academic [--auto-approve] [--resume] [--list-models] [task ...]
```

| Argument | Meaning |
| --- | --- |
| `task ...` | The task in natural language. Quoting is optional but recommended. Required unless `--list-models` or `--resume` is used. With `--resume` it is added as your next message. |
| `--auto-approve` | Run every proposed command without asking. See [Security](security.md). |
| `--resume` | Continue the last session of the current directory, for example after an API failure. See [Resuming a session](#resuming-a-session). |
| `--list-models` | Print the models available to your API client and exit. |

The agent works in the **current working directory**. Always `cd` into the
project first.

```bash
cd ~/projects/my-project
academic "Add a unit test for parse_date and run the test suite"
```

Pick a model for a single run without editing the config:

```bash
ACADEMIC_AI_MODEL=claude-opus-4-8 academic "Review setup.py for packaging mistakes"
```

## What a session looks like

```text
--- Agent step 1 ---

Proposed command:
  ls -la

Reason: Inspect the project layout.

Execute this command? [y/N] y

Command output:
...
Exit code: 0

--- Agent step 2 ---
```

Each step is one API request. Per step the model returns one of three actions:

| Action | What happens |
| --- | --- |
| `command` | The command and reason are printed. You confirm with `y`/`yes`; anything else rejects it and tells the model to propose a safer alternative. |
| `message` | The text is printed and you are asked `Continue? [y/N]`. Answering `y` tells the model to continue. Use this to read answers and questions from the model. |
| `done` | The summary is printed and the agent exits. |

A session stops after **30 steps**. Commands are killed after **300 seconds**,
and only the last 12,000 characters of output are returned to the model.

## Resuming a session

The connection to the API can be unreliable. The agent therefore retries a
failed request automatically (connection errors, timeouts, HTTP 429 and 5xx,
unparseable responses) up to 4 times, waiting 2, 5, 15 and 30 seconds. If all
retries fail it prints:

```text
Progress is saved. Continue with: academic --resume
```

Run `academic --resume` in the **same directory** to continue where it stopped.
Commands that already ran are not run again. `academic --resume "also update the
README"` adds your text as the next message. Without text, the agent just
continues the task.

### Where the session is stored

Before every API call the complete conversation history is written to

```text
${XDG_STATE_HOME:-~/.local/state}/academic-agent/<hash-of-directory>.json
```

- There is **one file per working directory**, overwritten at every step.
  Starting a new task in the same directory replaces the old session; sessions
  of different directories do not affect each other.
- The file is deleted when the task ends with `done`. Sessions that were
  aborted (`Ctrl+C`, closed terminal, API failure, step limit) stay on disk.
- Nothing is stored inside your project, so it does not show up in `git status`.

### Disk usage and cleanup

The file holds the same data that is sent to the API (see
[Security](security.md#what-is-sent-to-the-api)): the file listing (up to 2,000
paths), `AGENTS.md` contents and up to 12,000 characters of output per command.
Because the file is overwritten and not appended to, it stays small: typically
tens of KB, and at most a few hundred KB for a 30-step session. The total grows
only with the number of directories in which you left an unfinished session.

Check and clean up with:

```bash
du -sh ~/.local/state/academic-agent        # total size
ls -lt ~/.local/state/academic-agent        # sessions, newest first
rm ~/.local/state/academic-agent/*.json     # discard all saved sessions
```

Sessions are stored as plain text and may contain command output, so treat them
like shell history: delete them if a command printed secrets.

## Writing good tasks

- Be specific about the outcome: *"write only the number to count.txt"* beats
  *"count the lines"*.
- Ask the model to inspect before changing: *"Look at the failing test, explain
  the cause, then fix it."*
- Name the commands you want used: *"Run `pytest tests/test_io.py` to verify."*
- Split large jobs into several runs. Every step resends the entire history, so
  long sessions get slower and more expensive.
- To only ask a question, say so: *"Do not modify anything. Explain how the
  configuration is loaded."*

## Project instructions with `AGENTS.md`

The agent reads every `AGENTS.md` from the filesystem root down to the current
directory and includes the contents in the first message. Files closer to the
working directory come later and therefore take precedence. Use it for project
conventions:

```markdown
# AGENTS.md
- Use `pytest -q` to run tests; never run the integration tests.
- Python code is formatted with black (line length 100).
- Do not modify files under `data/`.
```

Because `AGENTS.md` content influences the commands the model proposes, review
files from untrusted repositories before running the agent there.

## What the model sees about your project

The first message contains the working directory, your task, the `AGENTS.md`
content and a **file listing** (paths only, up to 2,000 entries). The listing
skips hidden directories, `.git`, `.venv`, `venv`, `node_modules`,
`__pycache__`, `.cache`, `dist`, `build`, and files named `.env`, `.env.local`,
`.env.production`, `id_rsa`, `id_ed25519`. File **contents** are only sent when
a command such as `cat` outputs them, so anything the model reads is sent to the
API.

## Rejecting commands

If you answer `n`, the model is told the command was rejected and proposes
something else. You cannot type free-text feedback at the prompt; to give more
guidance, answer `n`, let the model respond with a `message`, or abort with
`Ctrl+C` and start again with a refined task.
