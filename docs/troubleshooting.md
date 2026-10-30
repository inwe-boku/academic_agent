# Troubleshooting

## Configuration errors

| Message | Cause and fix |
| --- | --- |
| `academic: command not found` | `~/.local/bin` is not on your PATH yet. Open a new terminal, or follow [Getting started, step 4](getting-started.md#4-put-academic-on-your-path). |
| `Not configured: ACADEMIC_AI_...` | The named variables are missing or still placeholders. Check that the config file exists at `~/.config/academic-agent/env` and that you start the agent through `academic`. |
| `Warning: ... is readable by group or others` | Run `chmod 600 ~/.config/academic-agent/env`. |
| `Error: virtual environment not found` | Run the commands in [Getting started](getting-started.md), step 2. |
| `stdin is not a terminal; non-interactive runs need --auto-approve.` | The agent was started from a script or pipe. Pass `--auto-approve` or run it in a terminal. |
| `ModuleNotFoundError: No module named 'requests'` | `.venv/bin/pip install -r requirements.txt` |

## HTTP errors

The agent prints `API error: Academic AI API returned HTTP <code>` followed by
the response body.

| Code | Typical cause |
| --- | --- |
| 400, `role: Input should be 'user' or 'assistant'` | A `system` role message was sent. The current code avoids this; if you modified the message construction, keep the system prompt inside a `user` message. |
| 400, invalid model | Wrong `ACADEMIC_AI_MODEL`. Pick a name from `academic --list-models`. |
| 400, unsupported parameter | A parameter that the chosen model does not support (see [API notes](api-reference.md)). |
| 401 | Wrong Client-ID or secret, a deactivated secret, or stray whitespace or quotes in the config file. |
| 403 | The client lacks `USE_API_LLM`. Ask your administrator. |
| 404 | Wrong path. Check `ACADEMIC_AI_BASE_URL` has no trailing `/api/v1`. |
| 422 | Request validation failed; read the body for the field name. |
| 429 or a rate-limit message | Rate limit of the API client reached. Wait a minute; ask the administrator for a higher limit. |
| 5xx | Platform or provider problem. Retry later, or try another model. |

## Network errors

Transient failures (connection errors, timeouts, HTTP 429/5xx) are retried
automatically up to 4 times. If the agent still stops with
`Progress is saved. Continue later with: academic --resume`, run `academic --resume`
in the same directory. See [Resuming a session](usage.md#resuming-a-session).

- `requests.exceptions.ConnectionError`: no connection, wrong host name, or the
  platform is only reachable from the university network or VPN.
- `Read timed out`: a request exceeded 180 s. Large reasoning models can be
  slow; try a smaller model or a smaller task.

Test the connection independently of the agent:

```bash
set -a; . ~/.config/academic-agent/env; set +a
curl -s "$ACADEMIC_AI_BASE_URL/api/v1/llm/models" \
  -H "X-Client-ID: $ACADEMIC_AI_CLIENT_ID" \
  -H "X-Client-Secret: $ACADEMIC_AI_CLIENT_SECRET" | head -c 400
```

## Behavior problems

| Symptom | Fix |
| --- | --- |
| `Invalid reply (...); asking the model to correct it.` | The model did not follow the JSON protocol. The agent corrects this automatically up to twice per turn. |
| `The model sent 3 invalid replies in a row` | Type an instruction to continue, or switch to a stronger model. |
| `... has not been read in this session` / `changed on disk since it was read` | Expected: the model must read a file before changing it. It usually recovers on its own. |
| `outside the project root` / `access to this file is not allowed` | The model tried to use a path outside the directory you started in, or a secret file. Start the agent in the right directory. |
| The result is slightly wrong, such as extra text in an output file | Make the task more precise (for example "write only the number"). |
| `TIMEOUT after 120 s` | A long-running command. The model can pass a `timeout` up to 600 s; ask for it, or run the command yourself and report the result. |
| Output seems cut off | Each result is capped at 200 lines / 20,000 characters (head and tail kept). The model can page with `read_file` offset/limit or filter output. |
| `Reached the step limit (100).` | Answer `y` to continue for another round, or split the task. |
| A command asks for approval despite `--auto-approve` | It was flagged as dangerous (shown above the prompt). This is intended; see [Security](security.md#dangerous-commands). |
| `/undo` says `cannot undo` for a file | The file had uncommitted changes when the agent started, or is not tracked by git. |

## Slow sessions

The spinner shows how long the current model request or shell command has
been running. When the task finishes (and with `/cost` at any prompt), a
`Time:` line shows where the session's time went:

```
Time: 6 steps · API 48.2s (7 calls, 1 retries, 2.0s retry wait) · tools 1.3s (5 actions) · session saves 0.01s · 1 invalid replies
```

- **API** is the time spent waiting for Academic AI, retry waits included.
  If it dominates, the model is slow: reasoning models (`gpt-5`, o-series)
  often take much longer per turn. Try a faster model for small tasks.
- **retry wait** is the backoff after transient errors (HTTP 429/5xx,
  network problems). A large value points to API overload or rate limits.
- **invalid replies** and **compactions** each cost one extra model request.
- **tools** is time spent in file tools and shell commands.

The per-step numbers are kept in the session file (`timings`); they contain
no prompt or output text.

## Still stuck?

Run `academic --list-models`. If that works, authentication and the host are
correct and the problem is in the chat request or the model's behavior. If it
fails, the problem is configuration or network.

??? tip "Reporting a bug"

    Open an issue at
    [github.com/inwe-boku/academic_agent/issues](https://github.com/inwe-boku/academic_agent/issues).
    Include the command you ran, the error message, the model name and the
    output of `git -C ~/.local/share/academic-agent log -1 --oneline` (your
    version). **Never paste your Client-Secret** or the content of the config
    file.

??? info "Are you on the latest version?"

    Some problems are already fixed in a newer version. See
    [Updating](getting-started.md#updating).
