# Usage

## Command line

```text
academic [--auto-approve] [--list-models] [task ...]
```

| Argument | Meaning |
| --- | --- |
| `task ...` | The task in natural language. Quoting is optional but recommended. Required unless `--list-models` is used. |
| `--auto-approve` | Run every proposed command without asking. See [Security](security.md). |
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
