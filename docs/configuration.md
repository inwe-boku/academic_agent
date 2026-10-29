# Configuration

All configuration is done through environment variables. The launcher script
`academic` loads them from a file before starting Python.

## Config file

Location: `${XDG_CONFIG_HOME:-$HOME/.config}/academic-agent/env`

The file is sourced by bash with automatic export, so it must contain
`export NAME='value'` lines (or plain `NAME=value`). Restrict access; the
launcher warns if the file is readable by group or others:

```bash
chmod 600 ~/.config/academic-agent/env
```

If you call `academic_agent.py` or `python -m academic_agent` directly instead of
using the launcher, the file is **not** read; export the variables yourself.

## Variables

| Variable | Required | Example | Description |
| --- | --- | --- | --- |
| `ACADEMIC_AI_BASE_URL` | yes | `https://<host>` | Host of the Academic AI backend. No `/api/v1`. |
| `ACADEMIC_AI_CLIENT_ID` | yes | `00000000-0000-0000-0000-000000000000` | Client-ID of your API client, sent as `X-Client-ID`. |
| `ACADEMIC_AI_CLIENT_SECRET` | yes | | Client-Secret, sent as `X-Client-Secret`. |
| `ACADEMIC_AI_MODEL` | yes | `gpt-5` | Model identifier from `--list-models` (not needed for `--list-models` itself). |
| `ACADEMIC_AI_REASONING_EFFORT` | no | `low` | `low`, `medium` or `high`; sent as `reasoningEffort` to reasoning models (o-series, gpt-5 family) only. Unset: the model's default. |

If one is missing, the agent stops and names it. None of these variables is
passed on to commands the agent runs. `NO_COLOR` disables colours; colours are
only used on a terminal anyway.

## Choosing a model

```bash
academic --list-models
```

Output columns are the model name, the context window in tokens, and the maximum
output tokens. Considerations:

- **Instruction following:** the agent depends on the model answering with one
  JSON object. Large general models (for example `gpt-5`, `claude-opus-*`,
  `gemini-*-pro`) are the safest choice. Search-oriented models such as `sonar-*`
  are a poor fit.
- **Context window:** used for the history budget; the history is compacted at
  70 % of it.
- **Speed:** time per turn is mostly the model's response time, and it grows
  with the output tokens, including hidden reasoning tokens. In measurements
  on a small task, `gpt-5` took 4–20 s per turn and `gpt-4o` 1–2 s. Use a
  non-reasoning model for quick tasks, or try
  `ACADEMIC_AI_REASONING_EFFORT=low`; its effect varied a lot between runs.
  The `Time:` line on the final screen shows where a session's time went (see
  [Troubleshooting](troubleshooting.md#slow-sessions)).
- **Cost:** per-token prices come from the models endpoint and drive the cost
  estimate; smaller models (`*-mini`, `*-nano`, `*-flash`) are cheaper for
  simple tasks.

## Values fixed in the code

| Value | Setting | Location |
| --- | --- | --- |
| Max turns per task | 100 (lower with `--max-steps`) | `loop.MAX_STEPS` |
| `run` timeout | 120 s default, 600 s max | `tools.DEFAULT_TIMEOUT`, `tools.MAX_TIMEOUT` |
| Tool output cap | 200 lines / 20,000 characters | `context.MAX_OUTPUT_*` |
| Initial listing | 3 levels / 300 entries | `context.INITIAL_*` |
| Compaction threshold | 70 % of the context window, keep 6 turns | `context.BUDGET_RATIO`, `context.KEEP_TURNS` |
| Invalid-reply retries | 2 per turn | `loop.MAX_INVALID_RETRIES` |
| API retries | 2, 5, 15, 30 s | `api.RETRY_DELAYS` |
| API request timeout | 180 s | `api.ApiClient._post_once` |

Other request parameters such as `temperature` are not sent, so the platform
defaults apply. They can be added to the payload in `ApiClient.chat()`; see
[API notes](api-reference.md).
