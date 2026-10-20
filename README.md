# Academic Agent

A small terminal coding agent for the BOKU **Academic AI** platform. Give it a
task in natural language; the model proposes shell commands, you approve each
one, the agent runs it locally and sends the output back until the task is done.

One Python file (`academic_agent.py`), one dependency (`requests`).

> Not an official BOKU product. API usage is billed separately from normal
> Academic AI accounts.

**Full documentation:** https://inwe-boku.github.io/academic_agent/
(sources in [`docs/`](docs/index.md))

## Quick Start

You need Python 3.9+, `bash`, and Academic AI API credentials (Client-ID,
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
academic "task description"                  # asks before every command
academic --auto-approve "task description"   # runs commands without asking
academic --list-models                       # list available models
```

The agent works in the **current directory**, so `cd` into the target project
first. Place an `AGENTS.md` in the project (or any parent directory) to give the
model standing instructions; all of them are included in the first prompt.

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

Each step (max. 30) the agent POSTs the full conversation to
`{BASE_URL}/api/v1/llm/chat` and expects a JSON action back:

| Action | Effect |
| --- | --- |
| `command` | Shows the command and reason, asks for approval, runs it (300 s timeout), returns the output to the model |
| `message` | Prints the text and asks whether to continue |
| `done` | Prints a summary and exits |

The API is stateless and only accepts the roles `user` and `assistant`, so the
system prompt is prepended to the first user message. That message also holds
the working directory, the task, a file listing (hidden directories, `.venv`,
`node_modules` and common secret files are skipped) and any `AGENTS.md` files.

## Safety

- Every command needs your approval unless you pass `--auto-approve`.
- Potentially dangerous commands are flagged with a warning (not blocked).
- Commands and their output are sent to the API; don't run it where secrets
  would be printed. Never commit your credentials.

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
| [Development](docs/development.md) | Extending the agent |

To preview the docs locally:

```bash
pip install "mkdocs<2" mkdocs-material
mkdocs serve
```
