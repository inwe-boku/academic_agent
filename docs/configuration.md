# Configuration

All configuration is done through environment variables. The launcher script
`academic` loads them from a file before starting Python.

## Config file

Location: `${XDG_CONFIG_HOME:-$HOME/.config}/academic-agent/env`

The file is sourced by bash with automatic export, so it must contain
`export NAME='value'` lines (or plain `NAME=value`). Restrict access:

```bash
chmod 600 ~/.config/academic-agent/env
```

If you call `academic_agent.py` directly instead of using the launcher, the file
is **not** read; export the variables in your shell yourself.

## Variables

| Variable | Required | Example | Description |
| --- | --- | --- | --- |
| `ACADEMIC_AI_BASE_URL` | yes | `https://<host>` | Host of the Academic AI backend. No trailing slash, no `/api/v1`. |
| `ACADEMIC_AI_CLIENT_ID` | yes | `00000000-0000-0000-0000-000000000000` | Client-ID of your API client, sent as `X-Client-ID`. |
| `ACADEMIC_AI_CLIENT_SECRET` | yes | | Client-Secret, sent as `X-Client-Secret`. |
| `ACADEMIC_AI_MODEL` | yes | `gpt-5` | Model identifier from `--list-models`. |

Until the placeholders `REPLACE_WITH_ACADEMIC_AI_BASE_URL` and
`REPLACE_WITH_MODEL_NAME` are replaced, the agent stops with an explanatory
error.

## Choosing a model

List what your client may use:

```bash
academic --list-models
```

Output columns are the model name, the context window in tokens, and the maximum
output tokens. Considerations:

- **Instruction following:** the agent depends on the model answering with
  strict JSON. Large general models (for example `gpt-5`, `claude-opus-*`,
  `gemini-*-pro`) are the safest choice. Search-oriented models such as `sonar-*`
  are a poor fit.
- **Context window:** the full history is resent each step. Long sessions
  need a large window.
- **Cost:** per-token prices come from the models endpoint; smaller models
  (`*-mini`, `*-nano`, `*-flash`) are cheaper for simple tasks.

## Values fixed in the code

These are constants in `academic_agent.py` rather than settings:

| Constant | Value | Location |
| --- | --- | --- |
| Max agent steps | 30 | `main()` |
| Command timeout | 300 s | `execute_command()` |
| Output returned to model | last 12,000 characters | `execute_command()` |
| API request timeout | 180 s | `call_academic_ai()` |
| File listing limit | 2,000 entries | `collect_context()` |

Request parameters such as `temperature` or `maxTokens` are not sent, so the
platform defaults apply. They can be added to the payload in
`call_academic_ai()`; see [API notes](api-reference.md).
