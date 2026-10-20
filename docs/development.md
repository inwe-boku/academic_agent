# Development

The code lives in the `academic_agent/` package; see
[How it works](how-it-works.md#code-layout) for the module layout. The only
runtime dependency is `requests`.

## Setup and tests

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The tests need no network: the API is faked. They cover path confinement, the
dangerous-command classifier, the file tools, protocol parsing, truncation and
the history budget, session permissions and redaction, `/undo`, and resuming
after an API failure. CI runs them on every pull request
(`.github/workflows/tests.yml`).

## Running without the launcher

```bash
set -a; . ~/.config/academic-agent/env; set +a
.venv/bin/python -m academic_agent --list-models
.venv/bin/python -m academic_agent "your task"
```

## Testing against a local mock

You can exercise the whole loop without credits by pointing
`ACADEMIC_AI_BASE_URL` at a local server that implements the two endpoints:

- `GET /api/v1/llm/models` returns `{"data": [{"modelName": ..., "contextWindow": ..., "outputTokenLimit": ..., "costs": [...]}]}`
- `POST /api/v1/llm/chat` returns `{"data": {"content": "<reply JSON as a string>", "usage": {"promptTokens": ..., "completionTokens": ...}}}`

Make the mock answer with an `actions` reply first and a `done` reply after
that.

## Common changes

**Add a tool.** Add its arguments to `TOOLS` and describe it in
`SYSTEM_PROMPT` (`protocol.py`), give it a tier in `policy.TIERS`, and implement
`_prep_<tool>()` in `tools.Executor`. Path arguments must go through
`Executor._resolve()`.

**Add request parameters.** Extend the payload in `ApiClient.chat()`. Check
[API notes](api-reference.md) for which models support which parameters.

**Extend the dangerous-command check.** Edit `_segment_dangerous()` in
`policy.py` and add positive and negative cases to `tests/test_policy.py`.

## Documentation

```bash
.venv/bin/pip install -r requirements-docs.txt
.venv/bin/mkdocs serve
```

The site is published by `.github/workflows/docs.yml` on pushes to `main`.
