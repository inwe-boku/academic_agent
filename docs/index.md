# Academic Agent

Academic Agent is a small terminal coding agent written in Python. It lets the
BOKU **Academic AI** platform act as a command-line assistant, similar in spirit
to other terminal coding agents, using only the platform's HTTP API.

You give it a task in natural language. The model reads and searches your
project with built-in file tools, proposes edits (shown as diffs) and shell
commands, and the agent asks for your approval before changing anything. Results
go back to the model until the task is done.

```bash
cd ~/projects/my-project
academic "Explain this project and list the most important missing documentation."
```

??? tip "New to the terminal?"

    Start with [Getting started](getting-started.md). It explains every step,
    including how to open a terminal and paste commands. Already installed?
    See [Updating](getting-started.md#updating) to get the latest version.

## Documentation

| Page | What it covers |
| --- | --- |
| [Getting started](getting-started.md) | Install, configure, first run (10 minutes), updating |
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

- **Small Python package**, one dependency (`requests`), tested with pytest.
- **Confined**: file tools only work inside the project root; secret files are
  never read.
- **Human in the loop**: file changes and commands need approval
  (`--accept-edits` and `--auto-approve` relax this; dangerous commands always
  ask). Changes can be reviewed with `/diff` and reverted with `/undo`.
- **Stateless API**: the conversation is resent on every turn and compacted when
  it grows large; nothing is stored on the platform side.
- **Model choice**: any chat model your API client can use (the platform lists
  GPT, Claude, Gemini, Mistral and Perplexity models).
- **Not an official BOKU product.** It is a community tool built on the
  documented Academic AI API. API usage is billed independently of normal
  Academic AI accounts.

## Limitations

- No native tool calling or streaming: the model replies with JSON text that
  the agent validates; invalid replies are corrected automatically.
- Shell commands are not sandboxed from the operating system; the approval
  prompt is the safeguard. See [Security](security.md).
- The API only accepts the roles `user` and `assistant`, so the system prompt is
  embedded in the first user message.
