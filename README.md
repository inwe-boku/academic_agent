# Academic Agent

A small terminal coding agent for the BOKU **Academic AI** platform. Give it a
task in natural language; the model reads your project with built-in file
tools, proposes edits (as diffs) and shell commands, you approve them, and the
agent sends the results back until the task is done.

A small Python package (`academic_agent/`), one dependency (`requests`).

> Not an official BOKU product. API usage is billed separately from normal
> Academic AI accounts.

**Full documentation:** https://inwe-boku.github.io/academic_agent/
(sources in [`docs/`](docs/index.md))

## Quick Start

You need Python 3.10+, `bash`, and Academic AI API credentials (Client-ID,
Client-Secret, API host). See
[Getting API access at BOKU](docs/boku-api-access.md) if you don't have them.

```bash
# 1. Get the code
git clone git@github.com:inwe-boku/academic_agent.git ~/.local/share/academic-agent
cd ~/.local/share/academic-agent

# 2. Install the dependency
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Configure credentials
mkdir -p ~/.config/academic-agent
cat > ~/.config/academic-agent/env <<'ENV'
export ACADEMIC_AI_BASE_URL="https://<academic-ai-host>"
export ACADEMIC_AI_CLIENT_ID="<client-id>"
export ACADEMIC_AI_CLIENT_SECRET="<client-secret>"
export ACADEMIC_AI_MODEL="<model-name>"
ENV
chmod 600 ~/.config/academic-agent/env

# 4. Put the launcher on your PATH
mkdir -p ~/.local/bin
ln -s "$PWD/academic" ~/.local/bin/academic

# 5. Check authentication and pick a model
academic --list-models

# 6. Run it inside a project
cd ~/projects/my-project
academic "Explain this project and list the most important missing documentation."
```

## Basic Usage

```bash
academic "task description"                  # asks before every change and command
academic --accept-edits "task description"   # applies file changes, asks for commands
academic --auto-approve "task description"   # asks only for dangerous commands
academic --resume                            # continue after a failure or stop
academic --sessions | --clear                # list / delete saved sessions
academic --list-models                       # list available models
```

The agent works in the **current directory** (the project root) and cannot
touch files outside it. Place an `AGENTS.md` in the project (or any parent
directory) to give the model standing instructions; all of them are included in
the first prompt.

At any prompt you can type `/diff` (changes by the agent), `/undo` (restore them
via git), `/cost` (token and cost totals) or `/quit`.

## Resuming a session

Failed API requests are retried automatically. If they keep failing, the
conversation is already saved and `academic --resume` (in the same directory)
continues where it stopped. Sessions are stored in
`${XDG_STATE_HOME:-~/.local/state}/academic-agent/` (mode 600, secrets redacted)
and deleted when you accept the final summary. See
[Usage](docs/usage.md#resuming-a-session).

## Configuration

| Variable | Meaning |
| --- | --- |
| `ACADEMIC_AI_BASE_URL` | Platform host, no trailing path |
| `ACADEMIC_AI_CLIENT_ID` | API client ID |
| `ACADEMIC_AI_CLIENT_SECRET` | API client secret |
| `ACADEMIC_AI_MODEL` | Model name (see `--list-models`) |

Variables can be set in the shell or in
`${XDG_CONFIG_HOME:-~/.config}/academic-agent/env`, which the launcher sources.

## How It Works

Each turn the agent POSTs the full conversation to
`{BASE_URL}/api/v1/llm/chat` and expects one JSON object back:

| Reply | Effect |
| --- | --- |
| `actions` | A batch of tool calls (`read_file`, `list_dir`, `search`, `edit_file`, `write_file`, `move_file`, `delete_file`, `run`), executed in order after approval |
| `question` | Asks you something and sends your answer back |
| `done` | Shows a summary, changed files, commands and costs |

Invalid replies are corrected automatically. Long histories are compacted with a
model-written summary at 70 % of the context window. See
[How it works](docs/how-it-works.md).

## Safety

- File tools are confined to the project root; `.git/`, `.env*`, `*.pem` and
  `id_*` are never accessible.
- File changes show a diff and need approval unless you pass `--accept-edits`
  or `--auto-approve`. Commands flagged as dangerous (deleting, resetting,
  pushing, network, installs, paths outside the project) always ask.
- Commands run in the project root without your API credentials or other secret
  environment variables, but they are **not** sandboxed.
- The agent may commit, push and open pull requests with `gh`; force pushes and
  commands that discard work are flagged. `/undo` reverts its file changes in
  the working tree (not commits or pushes).

See [Security](docs/security.md) and [Troubleshooting](docs/troubleshooting.md).

## Documentation

Browse online at https://inwe-boku.github.io/academic_agent/, or locally:

| Page | Covers |
| --- | --- |
| [Getting started](docs/getting-started.md) | Install, configure, first run |
| [Usage](docs/usage.md) | Commands, flags, writing good tasks |
| [Configuration](docs/configuration.md) | Environment variables, config file |
| [How it works](docs/how-it-works.md) | Agent loop and protocol |
| [API notes](docs/api-reference.md) | Platform endpoints used |
| [Security](docs/security.md) | Approval model, secrets, costs |
| [Troubleshooting](docs/troubleshooting.md) | Common errors |
| [Development](docs/development.md) | Tests, extending the agent |

To preview the docs locally:

```bash
pip install -r requirements-docs.txt
mkdocs serve
```
