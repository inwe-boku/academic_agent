# Academic Agent v2 — Specification (DRAFT)

Status: implemented (PR #2).

## 1. Goals

A command-line agent that works on the files of the current project through the
Academic AI chat API (stateless, no native tool calling, roles `user` and
`assistant` only).

| Goal | Meaning |
| --- | --- |
| **Fast** | Few API round trips; no unbounded context growth; file access in-process. |
| **Safe** | The model can only change files inside the project root, and every change is approved, reviewable and reversible. |
| **Clean** | No side effects the user did not ask for; small, tested modules. |

Non-goals: streaming, sub-agents, a web UI, OS-level sandboxing (a later option),
supporting other APIs.

## 2. Decisions taken

| Topic | Decision |
| --- | --- |
| Confinement | Path checks on all file tools; shell runs in project root with a scrubbed environment. No bwrap. |
| Tools | Dedicated file tools plus a shell tool for builds, tests and git. |
| Approval | Tiered (see 5). |
| Undo | Git-based. No own snapshots. |

## 3. Protocol

The model answers with **one JSON object** per turn. The agent requests
`responseFormat: {"type":"json_object"}` when the chosen model supports it.

```json
{"type": "actions", "reason": "why", "actions": [ <action>, ... ]}
{"type": "question", "question": "..."}
{"type": "done", "message": "summary"}
```

`message` as a standalone type is removed: a model that only wants to talk uses
`done` (final) or `question` (needs input).

### 3.1 Actions

| `tool` | Arguments | Effect | Tier |
| --- | --- | --- | --- |
| `read_file` | `path`, optional `offset`, `limit` (lines) | Return numbered lines | read |
| `list_dir` | `path`, optional `depth` (default 2) | Return tree, honours `.gitignore` | read |
| `search` | `pattern`, optional `path`, `glob` | Regex search (ripgrep if present, else Python) | read |
| `edit_file` | `path`, `old`, `new`, optional `replace_all` | Exact string replace; fails if `old` is missing or ambiguous | write |
| `write_file` | `path`, `content` | Create a file, or overwrite one already read this session | write |
| `move_file` | `from`, `to` | Rename within the project | write |
| `delete_file` | `path` | Delete one file (never directories) | write |
| `run` | `command`, optional `timeout` (default 120 s, max 600 s) | Shell command in project root | exec |
| `remember` | `text` | Append one durable project fact to `.academic/MEMORY.md` (see §8.1) | memory |

Rules:
- Several actions per turn are allowed. They run in order; the batch stops at
  the first failure or rejection. Each result is reported back.
- `edit_file` and `write_file` (overwrite) require that the file was read in
  this session and is unchanged on disk since (mtime + size check). This prevents
  blind edits.
- Results are structured text: `[1] read_file src/a.py: OK` followed by output.

### 3.2 Reply validation
The reply is parsed (fences and surrounding prose tolerated) and validated
against the schema above. On failure the agent sends a corrective message
(`Invalid reply: <error>. Respond with one JSON object.`) and retries, at most
2 times per turn, without involving the user.

## 4. Confinement

- All paths are resolved with `Path.resolve()` against the project root;
  anything outside (including via symlinks or `..`) is rejected before approval.
- Never readable or writable by file tools: `.git/`, `.env*`, `*.pem`, `id_*`.
  Secret-like filenames are denied, so they are never sent to the API.
- Files matched by `.gitignore` are skipped by `list_dir`, `search` and the
  initial listing. The model may still read or edit one by naming its path
  explicitly (unless it is secret-like).
- `run` executes with `cwd=root` and an environment stripped of
  `ACADEMIC_AI_*` and variables matching `*TOKEN*`, `*SECRET*`, `*KEY*`,
  `*PASSWORD*`.
- Shell commands are **not** isolated from the OS. This is documented as a
  limit; the approval prompt is the safeguard for `run`.

## 5. Approval (tiered)

| Tier | Default | `--accept-edits` | `--auto-approve` |
| --- | --- | --- | --- |
| read | auto | auto | auto |
| write | ask, shows unified diff | auto | auto |
| exec | ask | ask | auto |
| exec, flagged dangerous | ask | ask | **ask** |
| memory (`remember`) | auto, shown | auto, shown | auto, shown |

- **Dangerous** is decided on the parsed command (via `shlex`, per pipeline
  segment): `rm` with `-r`/`-f`, `git reset --hard`, `git clean`,
  `git checkout -- `, `git restore`, `git stash`, `git rebase`, force pushes
  and branch deletion via `git push`, `find -delete`, `sudo`, `dd`, `mkfs`, redirects to
  `/dev/*`, any path argument outside the project root, and any command
  containing `~` or `$HOME`. Network and install commands are flagged as well:
  `curl`, `wget`, `ssh`, `scp`, `rsync`, `nc`, `pip`/`pip3`/`uv pip install`,
  `npm`/`yarn`/`pnpm install|add`, `apt`/`apt-get`, `git clone|fetch|pull`. It is a safety net, not a guarantee.
  `git commit`, plain `git push` and `gh` (e.g. `gh pr create`) are **not**
  flagged: agents are intended to commit, push and open pull requests. Message
  arguments (`-m`, `--title`, `--body`) are exempt from the path checks.
- Prompt: `[y]es / [n]o / [a]lways this tool for the session / or type a
  comment to reject with feedback`. No "always" for dangerous commands.
- Non-interactive stdin (no TTY) without `--auto-approve` aborts with an error.
- `--json` (requires `--auto-approve`) never prompts: questions, dangerous
  commands, the step limit and errors end the run with a JSON result and a
  status-specific exit code (see docs/usage.md). `--resume --approve-blocked`
  approves exactly the blocked command once.

## 6. Git-based undo

- On start the agent records `git rev-parse HEAD` and whether the tree is clean.
- Not a git repo: the agent prints a prominent warning at start ("no git
  history: changes cannot be undone"). `--accept-edits` and `--auto-approve` are
  still allowed, but interactive runs ask for one explicit confirmation of the
  mode. `/undo` and `/diff` are unavailable.
- Dirty tree: warn once; the user may continue (undo is then limited to files
  that were clean at start).
- The agent may **commit, push and open pull requests** (`git`, `gh`) via `run`
  when the task or `AGENTS.md` asks for it. It never stashes, hard-resets,
  cleans or force-pushes on its own; `run` flags these as dangerous.
- `/undo` works on the working tree only; it does not revert commits or pushes.
- `/diff` shows `git diff` for files the agent touched. `/undo` restores those
  files that were clean at start (`git restore --source=<start> --worktree`), after confirming
  the list, and deletes files the agent created.
- The set of touched files is tracked in the session file.

## 7. Context and cost

- **Initial context:** cwd, task, AGENTS.md chain (as now), and a listing limited
  to 3 levels / 300 entries, honouring `.gitignore`. The model uses `list_dir`
  and `search` for more.
- **Tool output cap:** 200 lines or 20 000 characters per result, keeping head
  and tail, with a marker such as `[... 4 120 lines omitted, use offset/limit ...]`.
- **History budget:** the agent estimates tokens (chars / 3.5) and uses the
  `usage.promptTokens` of the last reply. At 70 % of the model's context window
  (from `/models`) the agent compacts the history with one extra API call: the
  model is asked to summarise everything except the first user message and the
  latest 6 turns (task, decisions, files read and changed with key facts, current
  state, open problems). The summary replaces those turns as a single user
  message. If the summary call fails, the fallback is one-line stubs for old tool
  results (`[read_file a.py: 212 lines, omitted]`), oldest first. The summary is
  shown to the user and stored in the session.
- **Step limit:** maximum 100 turns per task (default and ceiling; `--max-steps`
  may lower it). At the limit the agent stops and asks whether to continue for
  another 100.
- **Cost display:** after each turn a dim status line: tokens in/out, session
  total, estimated USD from `costs` of `/models`.
- **Retry:** unchanged (2, 5, 15, 30 s for network, 429, 5xx); `Retry-After` is
  honoured if present.

## 8. Sessions

- Stored in `${XDG_STATE_HOME:-~/.local/state}/academic-agent/`, directory mode
  700, file mode 600, atomic write (as now).
- Known secret patterns (`Bearer ...`, `sk-...`, `-----BEGIN ... KEY-----`,
  values of the stripped env vars) are redacted from tool results before they are
  stored or sent.
- Content: task, messages, touched files, start commit, token totals.
- Removed on `done` only after the user accepts it; kept otherwise.
- `--resume` unchanged; `--sessions` lists, `--clear` deletes.

### 8.1 Project memory
- `.academic/MEMORY.md` in the project root holds notes that the model saves
  with `remember` at any time, without approval. Every save prints
  `📝 Remembered: <text>`.
- Each entry is one line, `- <text>  (<date>)`, at most 1,000 characters.
  Duplicates (ignoring case and whitespace) are skipped. Notes that contain
  redactable secrets are refused. Beyond 16,000 characters the oldest entries
  are dropped. Writes are atomic. Both `.academic/MEMORY.md` and `.gitignore`
  must resolve inside the project root.
- In a git repository, the first save adds `.academic/` to the project's
  `.gitignore` once, so memory stays local and is never committed by
  accident.
- New sessions get the notes in the first message, after the AGENTS.md
  content (up to 8,000 characters; when truncated, the newest notes are
  kept). The notes are labelled as reference only: AGENTS.md and the user
  take precedence.
- The file is plain markdown: edit or delete it by hand. To change existing
  notes, the model uses `read_file`/`edit_file` with normal approval.

## 9. User interface

- The final screen of a task shows: summary from the model, files changed
  (`git status --short` scoped to touched files), commands run with exit codes,
  token and cost totals.
- Slash commands at any prompt: `/diff`, `/undo`, `/cost`, `/quit`.
- Colour only on a TTY; `NO_COLOR` respected. One `term_width()` helper.
- **Removed:** automatic post-run cleanup (deleting `*.bak`, `*.tmp`, ...),
  `compileall`, and `mkdocs build`. Checks and cleanup are things the user or
  `AGENTS.md` can request explicitly.
- Ctrl+C during a running command kills the process group and returns control to
  the prompt instead of exiting the agent.

## 10. Configuration

Single set of variables, used by launcher and code:

`ACADEMIC_AI_BASE_URL`, `ACADEMIC_AI_CLIENT_ID`, `ACADEMIC_AI_CLIENT_SECRET`,
`ACADEMIC_AI_MODEL`. The launcher warns if the config file is group- or
world-readable. The `academic` launcher fix: correct variable names and a clear
message when `.venv` is missing.

## 11. Code structure

```text
academic_agent/
  __main__.py      CLI, argument parsing
  loop.py          turn loop, dispatch
  api.py           HTTP, retry, usage
  protocol.py      schema, parsing, validation
  tools.py         file tools and run
  policy.py        path confinement, tiers, dangerous-command check
  context.py       initial context, truncation, history budget
  session.py       persistence, redaction
  ui.py            colours, prompts, spinner, diffs
tests/
```

`academic_agent.py` stays as a thin entry point so existing installs keep
working. Dependencies: `requests` only (docs tooling moves to
`requirements-docs.txt`).

## 12. Testing

pytest, no network (API faked). Required coverage:
- path confinement (symlink, `..`, absolute, `.git`, secret names)
- dangerous-command classifier (table of positive and negative cases)
- `edit_file` (missing, ambiguous, stale file) and diff output
- protocol parsing (fenced, prose around JSON, invalid)
- history budget and truncation
- session file permissions and redaction
- resume after simulated API failure

## 13. Migration and docs

- Update `docs/` (usage, security, how-it-works, configuration); fix the
  incorrect "30 steps" and `initial_prompt.md` mentions.
- Breaking changes: `message` reply type removed; post-run cleanup removed;
  `--auto-approve` no longer runs flagged commands unattended.

## 14. Implementation order

1. Package split and tests for existing behaviour (no functional change).
2. `policy` and `tools` (file tools, confinement, approvals).
3. Protocol v2 and validation.
4. Context budget, cost display.
5. Git undo, sessions hardening.
6. UI polish, docs.

## 15. Open questions

1. ~~Ignore file~~ — decided: `.gitignore` only.
2. ~~Non-git directories~~ — decided: allowed with a warning.
3. ~~History compaction~~ — decided: model-written summary (stubs as fallback).
4. ~~Network and install commands~~ — decided: flagged as dangerous.
5. ~~Step limit~~ — decided: 100.

No open questions remain.
