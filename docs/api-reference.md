# Academic AI API notes

A summary of the parts of the platform API (documentation v1.0.7) that the agent
uses. The authoritative source is the PDF documentation you get after logging in
to Academic AI.

## Authentication

Every request carries two headers:

```text
X-Client-ID: <client id>
X-Client-Secret: <client secret>
```

Endpoints are versioned under `/api/v1`. The base host is given on the BOKU API
page.

## Endpoints used by the agent

### `GET /api/v1/llm/models`

Lists models available to your client. Requires `USE_API_LLM`.

```json
{
  "data": [
    {
      "modelName": "gpt-5",
      "contextWindow": 400000,
      "outputTokenLimit": 128000,
      "costs": [
        {"costType": "input_tokens", "cost": 0.00138},
        {"costType": "output_tokens", "cost": 0.011}
      ]
    }
  ],
  "success": true
}
```

Prices are per 1,000 tokens (the values above are for `gpt-5`). `academic --list-models` prints name, context window
and output limit. The agent uses `contextWindow` for its history budget and
`costs` for the cost estimate.

### `POST /api/v1/llm/chat`

Non-streaming chat completion. Requires `USE_API_LLM`.

Request:

```json
{
  "model": "gpt-5",
  "messages": [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi!"},
    {"role": "user", "content": "And now?"}
  ]
}
```

Response (abridged):

```json
{
  "data": {
    "model": "gpt-5",
    "role": "assistant",
    "content": "...",
    "finishReason": "stop",
    "usage": {"promptTokens": 152, "completionTokens": 74, "totalTokens": 226}
  },
  "message": "Chat completion created successfully",
  "success": true
}
```

The agent reads `data.content` and `data.usage` (for the status line, the
history budget and the cost estimate).

**Message roles:** only `user` and `assistant` are accepted. A `system` message
is rejected with HTTP 400 (`role: Input should be 'user' or 'assistant'`).

**Optional parameters.** The agent sends `responseFormat: {"type": "json_object"}`
except for reasoning models (o-series, gpt-5 family); if the model rejects it
with HTTP 400, it retries without. With `ACADEMIC_AI_REASONING_EFFORT` set,
reasoning models also get `reasoningEffort` (again dropped after an HTTP
400/422). Other parameters can be added in
`ApiClient.chat()` (`academic_agent/api.py`):

| Parameter | Applies to | Notes |
| --- | --- | --- |
| `temperature` | all | 0.0 to 2.0 (scaled for Mistral) |
| `maxTokens` | standard OpenAI and Mistral models | response length limit |
| `maxCompletionTokens` | OpenAI reasoning models (o-series, gpt-5 family) | hard output limit |
| `reasoningEffort` | reasoning models | `low`, `medium`, `high` |
| `verbosity` | reasoning models | `low`, `medium`, `high` |
| `frequencyPenalty`, `presencePenalty` | all | -2.0 to 2.0 |
| `seed`, `responseFormat` | standard OpenAI and Mistral | `responseFormat` is `{"type": "json_object"}` for JSON mode |
| `stop` | Mistral only | |
| `tailoredAiId` | | Enables RAG with a Tailored AI (requires `USE_API_TAILORED_AI`) |

## JSON result of `academic --json`

Not part of the Academic AI API: this is the agent's own output format for
callers (see [Usage](usage.md#running-from-other-programs)). It is one object
on stdout:

```json
{
  "version": 1,
  "status": "blocked",
  "message": "An action needs the user's approval. ...",
  "blocked_action": "[2] run rm -rf build",
  "blocked_command": "rm -rf build",
  "reason": "rm -rf",
  "changed_files": ["src/a.py"],
  "run_log": [{"command": "pytest -q", "exit_code": 0}],
  "steps": 3,
  "tokens_in": 5120,
  "tokens_out": 410,
  "timings": [{"api_s": 4.48, "calls": 1, "retries": 0, "retry_wait_s": 0.0,
               "tools_s": 0.01, "tools": 2, "save_s": 0.001,
               "prompt_tokens": 1291, "completion_tokens": 332}],
  "session_kept": true
}
```

`status` is one of `done`, `error`, `question`, `blocked`, `step_limit`
and `interrupted`. `blocked_*` and `reason` appear only for `blocked`, and
`blocked_command` only when the blocked action is a `run`. `message` is
redacted like saved sessions. `steps` counts the steps of this invocation;
`timings` covers the whole session, one entry per step (see
[Troubleshooting](troubleshooting.md#slow-sessions)). New fields may be added within version 1.

## Endpoints not used

| Cluster | Prefix | Permission |
| --- | --- | --- |
| Cost | `/api/v1/cost` | `ACCESS_API_MONITOR_CREDIT` |
| Tailored AI | `/api/v1/tailored-ai` | `USE_API_TAILORED_AI` |
| Knowledge Base | `/api/v1/knowledge-base` | `USE_API_TAILORED_AI` |

## Error codes

| Status | Meaning |
| --- | --- |
| 400 | Invalid model or unsupported parameters (also invalid role) |
| 401 | Missing or invalid client credentials |
| 403 | Client lacks the required permission |
| 404 | Tailored AI or knowledge base not found |
| 422 | Validation error |
| 500 | Internal error |

The agent prints the status code and the first 4,000 characters of the response
body when a request fails.
