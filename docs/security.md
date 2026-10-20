# Security

The agent executes shell commands written by a language model. Treat it with the
same care as running a script you did not write.

## Approval model

- **Default:** every command is shown and requires `y` or `yes`.
- **`--auto-approve`:** commands run immediately. Use it only in disposable
  directories, containers or VMs, or in a Git repository on a dedicated branch
  with everything committed.
- Destructive-looking commands print a warning but are **not** blocked, even
  with `--auto-approve`.

Read the full command, not just the "Reason" line. The reason is model-written
text.

## Practical rules

- Commit or back up before running a task that modifies files.
- Work on a Git branch so you can review with `git diff`.
- Do not run the agent in your home directory or in directories containing
  secrets, SSH keys or private data.
- Be careful with `AGENTS.md` files in repositories you do not trust: their
  text is inserted into the prompt and can steer the model (prompt injection).
  The same applies to file contents, web pages or logs the model reads while
  working.
- Never approve commands that print credentials (`cat ~/.ssh/*`, `env`,
  `printenv`) and then send the output to the model.

## What is sent to the API

Everything in the conversation is transmitted to the Academic AI backend, which
forwards it to the underlying model provider:

- your task text and working directory path
- the file listing (paths, up to 2,000 entries)
- all `AGENTS.md` content
- the output of every command you approve (last 12,000 characters each)
- the model's own replies

Do not use the agent on data that must not leave BOKU's approved AI services.
Check BOKU's guidelines for the models you select, since different models are
hosted by different providers.

The automatic file listing skips hidden directories and common secret filenames
(`.env`, `id_rsa`, `id_ed25519`). This is a convenience, not a guarantee. File
contents are only sent if a command prints them.

## Saved sessions

To allow `--resume`, the full conversation is stored unencrypted in
`${XDG_STATE_HOME:-~/.local/state}/academic-agent/`, one JSON file per working
directory. It contains everything listed above, including the output of every
approved command, so a secret that was printed once is also on disk until the
task finishes with `done` or you delete the file. The file is created with your
default permissions (umask). See [Usage](usage.md#resuming-a-session) for size and
cleanup.

## Credentials

- Keep the Client-Secret in `~/.config/academic-agent/env` with mode `600`, not
  in the repository.
- Add local credential notes (such as `AAI_docs/api-zugangsdaten.txt`) to
  `.gitignore` before the first commit, and check with `git status` that they are
  untracked.
- If a secret leaks, ask your administrator to deactivate it and issue a new one.
  Clients can have two active secrets so rotation causes no downtime.
- The secret is sent as an HTTP header over HTTPS. Use only `https://` base URLs.

## Cost control

- API usage is billed separately from normal accounts and each API client has a
  configured **cost limit** and **rate limit**.
- The loop is capped at 30 steps, but each step resends the full history.
- A model that repeatedly proposes failing commands will keep consuming tokens
  until you stop it with `Ctrl+C` or by answering `n`.
