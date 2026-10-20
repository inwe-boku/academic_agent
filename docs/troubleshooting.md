# Troubleshooting

## Configuration errors

| Message | Cause and fix |
| --- | --- |
| `ACADEMIC_AI_CLIENT_ID / ACADEMIC_AI_CLIENT_SECRET are not set.` | The config file was not loaded. Check that it exists at `~/.config/academic-agent/env` and that you start the agent through `academic`, not `python academic_agent.py`. |
| `ACADEMIC_AI_BASE_URL is still a placeholder.` | Replace `REPLACE_WITH_ACADEMIC_AI_BASE_URL` with the real host. See [Getting API access](boku-api-access.md). |
| `.../.venv/bin/python: No such file or directory` | The virtual environment is missing. Run the commands in [Getting started](getting-started.md), step 2. |
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
`Progress is saved. Continue with: academic --resume`, run `academic --resume`
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
| The agent prints a long free-text answer and asks `Continue?` | The model did not follow the JSON protocol, so its text was shown as a `message`. Answer `y`; if it keeps happening, switch to a stronger model. |
| `Unrecognized model response:` | The JSON had an unknown `type`. Retry; use a stronger model. |
| `The model returned an invalid command.` | The `command` field was missing or empty. Retry the task. |
| The result is slightly wrong, such as extra text in an output file | Make the task more precise (for example "write only the number"). |
| `Command timed out after 300 seconds.` | A long-running command. Ask the model to run it in the background or in smaller parts, or run it yourself and report the result. |
| Output seems cut off | Only the last 12,000 characters are returned to the model. Ask it to filter output with `head`, `tail` or `grep`. |
| `Stopped after reaching the maximum number of agent steps.` | The task did not finish within 30 steps. Split it into smaller tasks. |
| Slow responses late in a session | The whole history is resent every step. Start a new run with a narrower task. |

## Still stuck?

Run `academic --list-models`. If that works, authentication and the host are
correct and the problem is in the chat request or the model's behavior. If it
fails, the problem is configuration or network.
