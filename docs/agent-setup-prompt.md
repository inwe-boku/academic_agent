# Agent setup prompt

Instead of following [Getting started](getting-started.md) by hand, you can give
the prompt below to a coding agent (for example Claude Code, Codex or Gemini CLI)
running on the target machine. The agent installs Academic Agent, writes the
config file, and verifies the connection.

## Before you start

Have these ready (see [Getting API access at BOKU](boku-api-access.md)):

- the repository URL
- the API host (base URL)
- the Client-ID and Client-Secret

**Do not paste the Client-Secret into the chat.** The prompt makes the agent
create the config file with a placeholder, and you enter the secret yourself in
an editor. This keeps the secret out of the agent's conversation history and
logs.

Replace the values in the `Inputs` section before sending the prompt.

## The prompt

````markdown
You are setting up "Academic Agent", a Python terminal coding agent for the BOKU
Academic AI platform, on this machine. Work step by step, report what you do,
and stop and ask me if something unexpected happens.

## Inputs

- Repository URL: git@github.com:inwe-boku/academic_agent.git
- Install directory: ~/.local/share/academic-agent
- API base URL: <API_BASE_URL>        (https, no trailing slash, no /api/v1)
- Client-ID: <CLIENT_ID>
- Default model: gpt-5

## Rules

- NEVER ask me for the Client-Secret, and never print, echo, log or read it
  back. I will enter it into the config file myself.
- Do not use sudo. If a system package is missing, tell me which one and stop.
- Do not modify files outside the install directory, ~/.config/academic-agent
  and ~/.local/bin, except for the one PATH line described in step 6.
- Do not overwrite existing files without showing me what exists first. If
  ~/.config/academic-agent/env already exists, keep it and only report which
  variables are present (names only, never values).
- Do not run `academic` with a real task and never use `--auto-approve`.
  Only `--list-models` is allowed for verification.

## Steps

1. Check prerequisites: `python3 --version` (3.10 or newer) and that the
   `venv` module works (`python3 -m venv --help`). Also check `git`.

2. Get the code. If the install directory does not exist, run
   `git clone git@github.com:inwe-boku/academic_agent.git ~/.local/share/academic-agent`. If it exists and
   is a git repository, run `git pull --ff-only`. Otherwise stop and ask.

3. Create the virtual environment in the install directory:
   `python3 -m venv .venv` and `.venv/bin/pip install -r requirements.txt`.
   Confirm with `.venv/bin/python -c "import requests"`.

4. Create the config file `~/.config/academic-agent/env` (skip if it exists):

   ```bash
   mkdir -p ~/.config/academic-agent
   cat > ~/.config/academic-agent/env <<'EOF'
   export ACADEMIC_AI_BASE_URL='<API_BASE_URL>'
   export ACADEMIC_AI_CLIENT_ID='<CLIENT_ID>'
   export ACADEMIC_AI_CLIENT_SECRET='PASTE_SECRET_HERE'
   export ACADEMIC_AI_MODEL='gpt-5'
   EOF
   chmod 600 ~/.config/academic-agent/env
   ```

   Verify the permissions are `-rw-------`.

5. Make the launcher available:
   `mkdir -p ~/.local/bin && ln -sf ~/.local/share/academic-agent/academic ~/.local/bin/academic`
   and make sure `academic` is executable (`chmod +x`).

6. Check whether `~/.local/bin` is on PATH (`echo "$PATH" | tr ':' '\n' | grep -x "$HOME/.local/bin"`).
   If not, append `export PATH="$HOME/.local/bin:$PATH"` to ~/.bashrc (or
   ~/.zshrc if my shell is zsh) and tell me to open a new shell.

7. Hand over to me for the secret. Tell me exactly this: "Open
   ~/.config/academic-agent/env in an editor, replace PASTE_SECRET_HERE with
   your Client-Secret, save, and tell me when you are done." Then wait.
   (Check with `grep -c PASTE_SECRET_HERE ~/.config/academic-agent/env`; it
   must print 0 before you continue. Do not display the file.)

8. Verify the connection: run `~/.local/bin/academic --list-models`.
   - Success: a list of models, one per line, including the default model.
   - On failure, diagnose without exposing secrets:
     - "not set" or "placeholder" message: a config variable is missing.
     - HTTP 401: wrong Client-ID or secret.
     - HTTP 403: the API client lacks the USE_API_LLM permission.
     - connection error: wrong host, or VPN/university network needed.
     Then stop and tell me what to fix. See docs/troubleshooting.md.
   - If the default model is not in the list, tell me and suggest an
     alternative from the list; do not change the config without asking.

9. Finish with a short report: what was installed and where, the Python version,
   whether PATH needs a new shell, the result of `--list-models`, and the next
   step: `cd` into a throwaway directory and run
   `academic "Create a file hello.txt containing the word hello"`, answering
   `y` to the proposed command.
````

## Notes

- The prompt only runs `academic --list-models`, which sends no project data
  and makes no billable chat request.
- If your agent cannot pause for input, run steps 1 to 6 with it, edit the
  config file yourself, then run `academic --list-models` manually.
- To install on a machine without internet access to the repository, copy the
  directory over and skip step 2; steps 3 to 8 are unchanged.
- Review the prompt before use. A coding agent runs the commands it generates,
  so check the repository URL and the install paths.
