# How it works

## Overview

```text
 you ── task ──▶ academic agent ── messages ──▶ Academic AI  /api/v1/llm/chat
                   ▲    │                                  │
     action results│    │ actions (JSON)                   │
                   │    ▼                                  ▼
          file tools / shell ◀── your approval ──  model reply (JSON)
```

The model never touches your machine directly. It proposes actions; the agent
checks them against the [policy](security.md), asks you where required, runs
them in-process (file tools) or in a shell (`run`) and sends the results back.

## The loop

Implemented in `academic_agent/loop.py` (`Agent`):

1. **Budget.** If the history exceeds 70 % of the model's context window, it is
   compacted (see [Context](#context-and-cost)).
2. **Save** the session, so the run can be resumed after any failure.
3. **Call the model** with the full history (`api.py`), retrying transient
   errors. `responseFormat: {"type": "json_object"}` is requested for models
   that support it.
4. **Validate** the reply (`protocol.py`). Code fences and prose around the JSON
   are tolerated. On a schema error the agent sends
   `Invalid reply: <error>. Respond with one JSON object.` and retries, at most
   twice, without involving you.
5. **Dispatch** on `type`:
   - `actions`: for each action, validate and preview it (path checks, diff,
     dangerous-command check), ask for approval if the tier requires it,
     execute. The batch stops at the first failure or rejection.
   - `question`: show it and send your answer.
   - `done`: show the final screen; finish or continue with a follow-up.

## Message protocol

The model answers with exactly one JSON object per turn:

```json
{"type": "actions", "reason": "why", "actions": [
  {"tool": "read_file", "path": "src/a.py"},
  {"tool": "edit_file", "path": "src/a.py", "old": "x = 1", "new": "x = 2"},
  {"tool": "run", "command": "pytest -q"}
]}
{"type": "question", "question": "Which test framework do you use?"}
{"type": "done", "message": "Added the test and it passes."}
```

The results go back as one `user` message, one block per action:

```text
[1] read_file src/a.py: OK
    1  x = 1

[2] edit_file src/a.py: OK
1 replacement(s)

[3] run pytest -q: FAILED (exit code 1)
exit code: 1
...
```

Rejected actions are reported as `REJECTED by user` with your comment;
actions after a failure or rejection as `SKIPPED`.

## Context and cost

- **Initial context:** the first `user` message holds the system prompt (the API
  accepts only the roles `user` and `assistant`), the project root, your task, a
  file listing (3 levels, 300 entries, `.gitignore` honoured) and all
  `AGENTS.md` files from `/` down to the project root.
- **Tool output** is capped at 200 lines or 20,000 characters per result,
  keeping head and tail.
- **History budget:** the agent estimates tokens from the `promptTokens` of the
  last reply plus characters / 3.5 for newer messages. At 70 % of the context
  window (from `/models`) it asks the model to summarise everything except the
  first message and the latest 6 turns. The summary is attached to the first
  message (so user and assistant messages keep alternating), shown to you and
  stored in the session. If the summary call fails, old tool results are
  replaced by stubs such as `[read_file a.py: 212 lines, omitted]`.
- **Cost:** the per-token prices from `/models` give the estimate shown after
  each turn.

## Stateless API

The platform keeps no conversation state. The agent holds the history and sends
all of it on each request. It is written to disk before every API call, so a
failed run can be continued with `academic --resume`.

## Code layout

| File | Role |
| --- | --- |
| `academic_agent/__main__.py` | CLI, argument parsing, start-up checks |
| `academic_agent/loop.py` | Turn loop, dispatch, approvals, slash commands |
| `academic_agent/api.py` | HTTP, retry, usage, model info |
| `academic_agent/protocol.py` | System prompt, schema, parsing, validation |
| `academic_agent/tools.py` | File tools and `run` |
| `academic_agent/policy.py` | Path confinement, tiers, dangerous-command check |
| `academic_agent/context.py` | Initial context, truncation, history budget |
| `academic_agent/memory.py` | Project memory (`.academic/MEMORY.md`), `.gitignore` entry |
| `academic_agent/session.py` | Persistence, redaction |
| `academic_agent/gitutil.py` | Git queries for undo, diff and listings |
| `academic_agent/ui.py` | Colours, prompts, spinner, diffs |
| `academic_agent.py` | Thin entry point kept for existing installs |
| `academic` | Launcher: loads the config file, runs the venv Python |
