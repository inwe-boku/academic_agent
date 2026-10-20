# Academic Agent

Academic Agent is a small terminal coding agent written in Python. It lets the
BOKU **Academic AI** platform act as a command-line assistant, similar in spirit
to other terminal coding agents, using only the platform's HTTP API.

You give it a task in natural language. The model decides which shell commands
are needed, the agent shows each command and asks for your approval, runs it
locally, and sends the output back to the model until the task is done.

```bash
cd ~/projects/my-project
academic "Explain this project and list the most important missing documentation."
```

## Documentation

| Page | What it covers |
| --- | --- |
| [Getting started](getting-started.md) | Install, configure, first run (10 minutes) |
| [Agent setup prompt](agent-setup-prompt.md) | Copy-paste prompt that lets a coding agent do the setup for you |
| [Getting API access at BOKU](boku-api-access.md) | Where the credentials, host and model names come from |
| [Usage](usage.md) | Commands, flags, writing good tasks, `AGENTS.md` |
| [Configuration](configuration.md) | Environment variables and the config file |
| [How it works](how-it-works.md) | Agent loop, message protocol, context handling |
| [Academic AI API notes](api-reference.md) | The parts of the platform API this tool uses |
| [Security](security.md) | Approval model, secrets, costs, what is sent to the API |
| [Troubleshooting](troubleshooting.md) | Common errors and fixes |
| [Development](development.md) | Working on the code, extending the agent |

## At a glance

- **One Python file** (`academic_agent.py`), one dependency (`requests`).
- **Stateless API**: the whole conversation is resent on every step; nothing is
  stored on the platform side.
- **Human in the loop**: every command needs a `y` unless you pass
  `--auto-approve`.
- **Model choice**: any chat model your API client can use (the platform lists
  GPT, Claude, Gemini, Mistral and Perplexity models).
- **Not an official BOKU product.** It is a community tool built on the
  documented Academic AI API. API usage is billed independently of normal
  Academic AI accounts.

## Limitations

- No tool calling or streaming: the model replies with JSON text and the agent
  parses it. Weaker models occasionally answer in free text; the agent then
  treats it as a message.
- No file-editing tool: all changes happen through shell commands the model
  proposes.
- The API only accepts the roles `user` and `assistant`, so the system prompt is
  embedded in the first user message.
- Working directory context is a file listing only; the model reads file
  contents by asking to run commands such as `cat`.
