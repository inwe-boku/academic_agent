# Development

The project has no build step, linter or test suite. Everything lives in
`academic_agent.py`.

## Layout of `academic_agent.py`

| Function | Responsibility |
| --- | --- |
| `api_headers()` | Validates configuration and builds auth headers |
| `call_academic_ai(messages)` | The only chat request; returns the assistant text. Change here if the API changes |
| `list_models()` | `GET /api/v1/llm/models` |
| `find_agents_files()`, `read_agents_files()` | Collect `AGENTS.md` instructions |
| `collect_context()` | File listing for the first prompt |
| `build_initial_prompt()` | Assembles cwd, task, listing and `AGENTS.md` |
| `parse_model_response()` | Extracts the JSON action from a reply |
| `command_is_potentially_dangerous()` | Warning heuristics |
| `execute_command()` | Runs a shell command with timeout and output cap |
| `main()` | Argument parsing and the agent loop |

## Running without the launcher

```bash
set -a; . ~/.config/academic-agent/env; set +a
.venv/bin/python academic_agent.py --list-models
.venv/bin/python academic_agent.py "your task"
```

## Testing against a local mock

You can exercise the whole loop without credits by pointing
`ACADEMIC_AI_BASE_URL` at a local server that implements the two endpoints:

- `GET /api/v1/llm/models` returns `{"data": [{"modelName": ..., "contextWindow": ..., "outputTokenLimit": ...}]}`
- `POST /api/v1/llm/chat` returns `{"data": {"content": "<json action as a string>"}}`

and requires non-empty `X-Client-ID` and `X-Client-Secret` headers. Make the
mock answer with a `command` action first and a `done` action once the request
contains `Exit code`.

## Common changes

**Add request parameters.** Extend the payload in `call_academic_ai()`:

```python
json={"model": MODEL, "messages": messages, "temperature": 0.2},
```

Check [API notes](api-reference.md) for which models support which parameters.

**Add an action type.** Update both the JSON forms in `SYSTEM_PROMPT` and the
dispatch in `main()`, so that the model knows about it and the loop handles it.

**Change limits.** Step count, timeouts and output caps are literals in `main()`,
`call_academic_ai()` and `execute_command()`; see
[Configuration](configuration.md).

**Support another backend.** Only `call_academic_ai()` and the environment
variables are Academic AI specific. Any chat API that returns plain text can be
used by changing that function.

## Publishing the documentation

The `docs/` folder consists of plain Markdown with relative links, so it renders
directly on GitHub. To publish it as a site, enable **GitHub Pages** in the
repository settings with the source set to the `main` branch and the `/docs`
folder. Before the first commit, make sure `.gitignore` excludes credentials
(see [Security](security.md)).
