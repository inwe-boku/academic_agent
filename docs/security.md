# Security

The agent lets a language model read and change files and run shell commands.
Treat it with the same care as running a script you did not write.

## What the agent enforces

- **Confinement of file tools.** Every path is resolved against the project root
  (the directory you start the agent in). Anything outside, including via
  symlinks or `..`, is rejected before you are asked.
- **Secret files.** `.git/`, `.env*`, `*.pem` and `id_*` can never be read or
  written by file tools, so their contents are not sent to the API through them.
- **Read before write.** Existing files can only be edited or overwritten after
  the model has read them in this session and only if they did not change on
  disk since.
- **Tiered approval.** Reads are automatic; file changes show a diff and ask;
  shell commands ask. See [Usage](usage.md#approval).
- **Scrubbed environment.** `run` executes in the project root with
  `ACADEMIC_AI_*` and every variable whose name contains `TOKEN`, `SECRET`,
  `KEY` or `PASSWORD` removed.
- **Redaction.** Bearer tokens, `sk-...` keys, private key blocks and the values
  of the removed variables are replaced by `[REDACTED]` in tool results before
  they are sent or stored.
- **Git-based undo.** The agent never commits, stashes, resets or cleans; `/undo`
  restores the files it touched. See [Usage](usage.md#undo-with-git).

## Dangerous commands

A command is flagged as dangerous after parsing it (with `shlex`, per pipeline
segment, including `bash -c`, `find -exec` and `xargs`) if it contains:

- `rm` with `-r`/`-f`, `find -delete`, `sudo`, `dd`, `mkfs`, redirects to
  `/dev/*` (except `/dev/null`)
- `git reset`, `git clean`, `git checkout -- `, `git restore`, `git stash`,
  `git commit`, `git rebase`, `git push`, `git pull`, `git fetch`, `git clone`
- network and install commands: `curl`, `wget`, `ssh`, `scp`, `rsync`, `nc`,
  `pip install`, `uv pip install`, `npm`/`yarn`/`pnpm install|add`,
  `apt`/`apt-get`
- any path argument outside the project root, and any reference to `~` or
  `$HOME`

Flagged commands always ask, **even with `--auto-approve`**, and cannot be
approved with "always". This is a safety net, not a guarantee: a script or
program can do anything its author wrote.

## Limits

- **Shell commands are not isolated from the operating system.** A command you
  approve runs with your user's permissions. The approval prompt is the
  safeguard for `run`; read the full command, not just the model's reason.
- `--auto-approve` runs unflagged commands without asking. Use it only in
  disposable directories, containers or VMs, or in a git repository with
  everything committed.
- Prompt injection: `AGENTS.md` files, file contents, logs and command output
  the model reads can steer it. Be careful in repositories you do not trust.

## What is sent to the API

Everything in the conversation goes to the Academic AI backend, which forwards
it to the model provider:

- your task text and the project root path
- the initial file listing (paths, up to 300 entries) and `AGENTS.md` content
- the result of every action: file contents the model reads, search matches,
  command output (capped at 200 lines or 20,000 characters each)
- the model's own replies and, when the history is compacted, its summary

Do not use the agent on data that must not leave BOKU's approved AI services.
Check BOKU's guidelines for the models you select, since different models are
hosted by different providers.

## Saved sessions

To allow `--resume`, the conversation is stored unencrypted in
`${XDG_STATE_HOME:-~/.local/state}/academic-agent/` (directory mode `700`, file
mode `600`). It contains everything listed above after redaction. It is deleted
when you accept the final screen; otherwise remove it with `academic --clear`.

## Credentials

- Keep the Client-Secret in `~/.config/academic-agent/env` with mode `600`, not
  in the repository. The launcher warns if the file is group- or world-readable.
- Add local credential notes (such as `AAI_docs/api-zugangsdaten.txt`) to
  `.gitignore` before the first commit, and check with `git status` that they are
  untracked.
- If a secret leaks, ask your administrator to deactivate it and issue a new one.
- The secret is sent as an HTTP header over HTTPS. Use only `https://` base URLs.

## Cost control

- API usage is billed separately from normal accounts; each API client has a
  configured **cost limit** and **rate limit**.
- A status line after every turn shows tokens and the estimated cost; `/cost`
  shows the totals.
- After 100 turns (or `--max-steps`) the agent asks before continuing. The
  history is compacted at 70 % of the context window.
