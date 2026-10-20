# Getting started

> Prefer to let a coding agent do this? Use the [agent setup prompt](agent-setup-prompt.md).

## Prerequisites

- Linux or macOS with `bash`
- Python 3.9 or newer (`python3 --version`)
- Credentials for an Academic AI **API client** (Client-ID and Client-Secret) and
  the API host. See [Getting API access at BOKU](boku-api-access.md) if you do
  not have these yet.

## 1. Get the code

Clone or copy the repository to a permanent location, for example:

```bash
git clone <your-repository-url> ~/.local/share/academic-agent
cd ~/.local/share/academic-agent
```

The directory contains:

| File | Purpose |
| --- | --- |
| `academic_agent.py` | The agent |
| `academic` | Bash launcher that loads your config and starts the agent |
| `requirements.txt` | Python dependencies |

## 2. Create the virtual environment

The launcher expects a virtual environment named `.venv` next to it.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 3. Configure credentials

The launcher sources `~/.config/academic-agent/env` if it exists (or
`$XDG_CONFIG_HOME/academic-agent/env`). Create it and restrict its permissions:

```bash
mkdir -p ~/.config/academic-agent
cat > ~/.config/academic-agent/env <<'EOF'
export ACADEMIC_AI_BASE_URL='https://<host-of-the-academic-ai-backend>'
export ACADEMIC_AI_CLIENT_ID='<your client id>'
export ACADEMIC_AI_CLIENT_SECRET='<your client secret>'
export ACADEMIC_AI_MODEL='gpt-5'
EOF
chmod 600 ~/.config/academic-agent/env
```

Use the host **without** a trailing slash and without the `/api/v1/...` part.
All variables are described in [Configuration](configuration.md).

## 4. Put `academic` on your PATH

```bash
mkdir -p ~/.local/bin
ln -s ~/.local/share/academic-agent/academic ~/.local/bin/academic
```

The launcher resolves symlinks, so it finds its `.venv` and `academic_agent.py`
correctly. Make sure `~/.local/bin` is on your `PATH`:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

## 5. Verify the connection

```bash
academic --list-models
```

You should see one line per available model:

```text
gpt-5  context=400000  max_output=128000
claude-opus-4-8  context=1000000  max_output=128000
...
```

If this fails, see [Troubleshooting](troubleshooting.md). Typical causes are a
wrong host, a typo in the secret, or an API client without the `USE_API_LLM`
permission.

## 6. First task

Use a throwaway directory for the first run:

```bash
mkdir /tmp/agent-test && cd /tmp/agent-test
echo "hello world" > a.txt
academic "Count the words in a.txt and write only the number to count.txt"
```

For every command the model proposes you will see:

```text
Proposed command:
  wc -w < a.txt > count.txt

Reason: Count words and write the result.

Execute this command? [y/N]
```

Answer `y` to run it. The result is sent back to the model, which either
proposes the next command or finishes with a summary.

## Next steps

- [Usage](usage.md): flags, writing tasks, project instructions via `AGENTS.md`
- [Security](security.md): read this before using `--auto-approve`
