# Getting started

This page installs Academic Agent step by step. It takes about 10 minutes.
Every command below is typed (or pasted) into a terminal.

> Prefer to let a coding agent do this? Use the [agent setup prompt](agent-setup-prompt.md).

??? tip "New to the terminal? Read this first"

    - **Open a terminal.** On Linux press ++ctrl+alt+t++ or search for
      "Terminal" in the applications menu. On macOS open *Spotlight*
      (++cmd+space++), type "Terminal" and press Enter.
    - **Copy and paste.** Use the copy button in the top right corner of each
      code block. Paste into the terminal with ++ctrl+shift+v++ (Linux) or
      ++cmd+v++ (macOS), then press Enter. You can paste a whole block at once.
    - **`~` is your home folder**, for example `/home/anna` on Linux or
      `/Users/anna` on macOS. `~/.config` is the hidden folder `.config` in it.
    - **Text in angle brackets is a placeholder.** Replace `<your client id>`
      (including the `<` and `>`) with your own value before pressing Enter.
    - **No output usually means success.** Many commands print nothing when
      they work. Error messages are printed in plain words; look them up in
      [Troubleshooting](troubleshooting.md).
    - **Lines starting with `#`** inside a code block are comments and do
      nothing.

## Prerequisites

- Linux or macOS with `bash`
- Python 3.10 or newer (`python3 --version`)
- `git` (`git --version`)
- Credentials for an Academic AI **API client** (Client-ID and Client-Secret) and
  the API host. See [Getting API access at BOKU](boku-api-access.md) if you do
  not have these yet.

??? info "How to check and install the prerequisites"

    Run these two commands:

    ```bash
    python3 --version
    git --version
    ```

    Each should print a version number, for example `Python 3.12.3`. If the
    Python version is lower than 3.10, or a command is not found:

    - **Ubuntu/Debian:** `sudo apt install python3 python3-venv git`
    - **macOS:** run `xcode-select --install` for `git`, and install Python
      from [python.org](https://www.python.org/downloads/) or with Homebrew
      (`brew install python`).

    On a managed university computer, ask your IT support if you cannot
    install software yourself.

## 1. Get the code

Download the repository to a permanent location and go into it:

```bash
git clone git@github.com:inwe-boku/academic_agent.git ~/.local/share/academic-agent
cd ~/.local/share/academic-agent
```

??? tip "`Permission denied (publickey)`? Use the HTTPS address instead"

    The address above needs an SSH key registered with GitHub. Without one,
    download over HTTPS:

    ```bash
    git clone https://github.com/inwe-boku/academic_agent.git ~/.local/share/academic-agent
    cd ~/.local/share/academic-agent
    ```

??? info "What is in the directory?"

    | File | Purpose |
    | --- | --- |
    | `academic_agent/` | The agent (Python package) |
    | `academic_agent.py` | Entry point used by the launcher |
    | `academic` | Bash launcher that loads your config and starts the agent |
    | `requirements.txt` | Python dependencies |

    You can install to another directory. Then replace
    `~/.local/share/academic-agent` with your path in all later commands.

## 2. Create the virtual environment

The launcher expects a virtual environment named `.venv` next to it. Run this
inside the directory from step 1:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The second command prints download progress and ends with
`Successfully installed ...`.

??? info "What is a virtual environment?"

    A virtual environment is a private Python installation in the folder
    `.venv`. The agent's dependencies are installed there, so they do not mix
    with other Python programs on your computer. Deleting the folder removes
    them again. You never need to "activate" it: the `academic` launcher uses
    it automatically.

## 3. Configure credentials

The launcher reads your credentials from the file `~/.config/academic-agent/env`
(or `$XDG_CONFIG_HOME/academic-agent/env`). Replace the three placeholders in
the block below with your values, then paste it into the terminal:

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

??? tip "Prefer a text editor? Create the file with `nano`"

    Pasting the secret into the terminal can leave it in your shell history.
    To avoid that, paste the block above with the placeholders unchanged, then
    open the file in an editor:

    ```bash
    nano ~/.config/academic-agent/env
    ```

    Replace the placeholders, save with ++ctrl+o++ and Enter, and quit with
    ++ctrl+x++. Keep the single quotes around each value.

??? info "What does `chmod 600` do?"

    It makes the file readable and writable only by you, so other users on the
    same computer cannot read your Client-Secret. The launcher prints a warning
    if the file is readable by others.

## 4. Put `academic` on your PATH

This makes the command `academic` available in every directory:

```bash
mkdir -p ~/.local/bin
ln -s ~/.local/share/academic-agent/academic ~/.local/bin/academic
```

The launcher resolves symlinks, so it finds its `.venv` and `academic_agent.py`
correctly. Now make sure your shell looks in `~/.local/bin`. On **Linux**
(bash):

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

On **macOS** the default shell is zsh, so use `~/.zshrc` instead:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

??? info "What is the PATH, and how do I know which shell I use?"

    The PATH is the list of folders the terminal searches when you type a
    command. Adding `~/.local/bin` to it lets you type `academic` instead of
    the full path to the launcher.

    Run `echo $SHELL` to see your shell: `/bin/bash` means bash (`~/.bashrc`),
    `/bin/zsh` means zsh (`~/.zshrc`). Terminals that were already open do not
    see the change until you run the `source` command or open a new one.

??? tip "`ln: failed to create symbolic link: File exists`"

    You already created the link in an earlier attempt. That is fine; skip
    this command.

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
permission. This command sends no project data and costs nothing.

## 6. First task

Use a throwaway directory for the first run:

```bash
mkdir /tmp/agent-test && cd /tmp/agent-test
echo "hello world" > a.txt
academic "Count the words in a.txt and write only the number to count.txt"
```

The model reads files on its own. For every change and command it proposes you
will see something like:

```text
  Count the words and write the result.
[1/1] write_file count.txt
--- a/count.txt
+++ b/count.txt
@@ -0,0 +1 @@
+2
Approve? [y]es / [n]o / [a]lways write_file / or type a comment to reject:
```

Answer `y` to apply it, or type a comment to reject it with feedback. The result
is sent back to the model, which continues or finishes with a summary. Accept
the final screen with `y` to end the task.

??? info "How to read the proposed change"

    The block between `---` and `Approve?` is a *diff*: lines starting with `+`
    would be added, lines starting with `-` would be removed. Here the agent
    wants to create `count.txt` containing the single line `2`.

??? tip "Stopping at any time"

    Press ++ctrl+c++ or type `/quit` at any prompt. Nothing more happens, and
    you can continue later with `academic --resume` in the same directory.

## Updating

When a new version is available, update your installation in the directory
from step 1. Your config file (`~/.config/academic-agent/env`) and the
`academic` link live outside this directory and are not changed.

```bash
cd ~/.local/share/academic-agent
git pull --ff-only
.venv/bin/pip install -r requirements.txt
academic --list-models
```

`git pull` downloads the new version. The `pip install` step only changes
something when the dependencies changed, so it is safe to run every time. The
last command checks that the agent still starts and reaches the API.

??? tip "Check whether an update is available, and what changed"

    ```bash
    cd ~/.local/share/academic-agent
    git fetch
    git status -sb                 # "[behind 3]" means 3 new changes
    git log --oneline HEAD..@{u}   # one line per new change
    ```

    If `git status -sb` shows no `[behind ...]`, you are up to date.

??? info "`git pull` refuses with \"Not possible to fast-forward\" or \"Your local changes would be overwritten\""

    You (or a tool) edited files in the install directory. See which ones:

    ```bash
    git status
    ```

    To keep your edits aside, run `git stash` and then `git pull --ff-only`
    again. To throw them away instead, run `git restore <file>` for each file
    listed, then pull again.

??? info "`academic` fails after a system Python upgrade"

    A virtual environment is tied to the Python version that created it.
    Recreate it in the install directory:

    ```bash
    cd ~/.local/share/academic-agent
    rm -rf .venv
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    ```

## Next steps

- [Usage](usage.md): flags, writing tasks, project instructions via `AGENTS.md`
- [Security](security.md): read this before using `--auto-approve`
