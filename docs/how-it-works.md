# How it works

## Overview

```text
 you ── task ──▶ academic_agent.py ── messages ──▶ Academic AI  /api/v1/llm/chat
                      ▲  │                                  │
        command output│  │ proposed command (JSON)          │
                      │  ▼                                  ▼
                 local shell  ◀── your approval ──   model reply (JSON)
```

The model never touches your machine directly. It can only *propose* a shell
command; the agent displays it, asks you, and executes it locally with the
working directory set to where you started the agent.

## The loop

Implemented in `main()` in `academic_agent.py`, at most 30 iterations:

1. **Call the model.** `call_academic_ai(messages)` sends the whole message list
   and returns the assistant text from `data.content`.
2. **Parse.** `parse_model_response()` removes optional Markdown code fences and
   parses JSON. If parsing fails, the raw text is treated as a `message`.
3. **Dispatch** on the `type` field:
   - `command`: print, warn if it looks destructive, ask for approval (unless
     `--auto-approve`), execute, append the result to the history.
   - `message`: print, ask whether to continue.
   - `done`: print the summary and exit.
   - anything else: print the raw reply and exit with an error.

## Message protocol

`SYSTEM_PROMPT` instructs the model to answer with JSON only:

```json
{"type": "command", "command": "ls -la", "reason": "Inspect the project"}
{"type": "message", "message": "Which test framework do you use?"}
{"type": "done",    "message": "Added the test and it passes."}
```

After a command runs, the agent adds two history entries:

- `assistant`: the model's original reply
- `user`: `The command was: ...  Exit code: N  Output: ...`

A rejected command produces a user message saying the command was rejected and
asking for a safer alternative.

## Initial context

The first `user` message is assembled from:

1. `SYSTEM_PROMPT` (rules and the JSON protocol). The API accepts only the
   roles `user` and `assistant`, so there is no separate system message.
2. The current working directory and your task.
3. A file listing from `collect_context()`.
4. The contents of all `AGENTS.md` files from `/` down to the working directory
   (`find_agents_files()`), more specific files last.

## Stateless API

The platform does not keep conversation state. The agent holds the `messages`
list in memory and sends all of it on each request. Consequences:

- Input tokens, and therefore cost and latency, grow with every step.
- Because the history exists only in the agent, it is written to disk before
  every API call (`save_session()`), so a failed run can be continued with
  `academic --resume`. Failed requests are first retried with backoff
  (`call_academic_ai()`, `RETRY_DELAYS`). The file is removed on `done`. See
  [Usage](usage.md#resuming-a-session).
- Without `--resume`, each `academic ...` call starts a fresh session and
  replaces the saved one for that directory.

## Safety layer

`command_is_potentially_dangerous()` checks the proposed command for fragments
such as `rm -rf`, `rm -r`, `git reset --hard`, `git clean`, `mkfs`, `dd if=`,
`shutdown`, `reboot`, `poweroff`, `sudo ` and `> /dev/`. A match only prints a
warning; the confirmation prompt is the real safeguard. It is a simple
substring check and is easy to bypass accidentally (for example with a script
that contains such a command), so always read what you approve.

## Files

| File | Role |
| --- | --- |
| `academic_agent.py` | Entire implementation |
| `academic` | Launcher: loads config file, runs the venv Python |
| `initial_prompt.md` | Historical design notes from the first draft, including an older version of the script. `academic_agent.py` is authoritative. |
