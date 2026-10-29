# Implementation Plan: Issue #4 — Make Academic Agent Faster

## Objective

Investigate and resolve cases where Academic Agent sessions are unexpectedly slow, even when the requested task is small. Preserve correctness, retry behavior, safety prompts, session persistence, and user-visible progress reporting.

## Current architecture relevant to latency

- `academic_agent/loop.py` drives the turn loop and may perform up to 100 steps.
- Before each model request, the agent calls `_ensure_budget()` and saves the session.
- `academic_agent/api.py` performs HTTP requests with a 180-second request timeout and retries transient failures using delays of 2, 5, 15, and 30 seconds.
- `academic_agent/context.py` manages history budgeting, compaction, summaries, stubbing, and truncation.
- `academic_agent/session.py` serializes the complete session to JSON on every save.
- `academic_agent/tools.py` executes shell and file operations, including commands with a maximum timeout of 600 seconds.

## Phase 1: Establish reproducible evidence

1. Reproduce the reported slowness using a small, deterministic task and record:
   - Time spent before the first model request.
   - API request duration and response status.
   - Time spent in retries and retry delays.
   - Time spent in context budgeting or compaction.
   - Time spent saving/loading session state.
   - Time spent executing tools, including shell commands.
   - Number of agent steps and total input/output tokens.
2. Add lightweight, opt-in or debug-level timing instrumentation around these boundaries. Avoid logging prompts, secrets, or full tool output.
3. Add tests that verify timing instrumentation does not alter behavior and that the measured stages are reported consistently.

## Phase 2: Inspect and isolate likely causes

Investigate each category rather than assuming the API is the only source:

- **API latency:** request timeout behavior, retry classification, retry-after handling, repeated model metadata requests, and whether a request is unintentionally repeated.
- **Context growth:** repeated serialization or excessive history sent to the model, unnecessary compaction, and expensive message transformations.
- **Session persistence:** repeated full-session JSON writes, filesystem delays, and whether saves happen more often than required.
- **Tool execution:** shell commands that wait unnecessarily, process timeout handling, and commands invoked by the agent that are unrelated to the task.
- **Turn-loop behavior:** invalid-response retries, follow-up loops, max-step handling, and any accidental busy/wait cycle.
- **User interface:** spinner or rendering code that blocks the loop or gives the appearance of a hung request.

Use profiling or targeted instrumentation only while diagnosing; do not retain noisy production logging.

## Phase 3: Implement the smallest safe fixes

Implement only fixes supported by measurements. Candidate changes may include:

- Avoiding redundant API or model-information calls.
- Reducing unnecessary context processing while preserving the configured history budget.
- Making session saves atomic and efficient without weakening persistence guarantees.
- Correcting retry or timeout behavior if requests are repeated or delayed incorrectly.
- Preventing avoidable tool invocations or reducing unnecessary process overhead.
- Improving progress reporting so unavoidable network or tool latency is clearly distinguished from a stalled session.

Do not remove retries, safety checks, context limits, or persistence solely to improve apparent speed.

## Phase 4: Regression coverage

Add or update tests for:

- API calls, retries, retry-after handling, and request timeout configuration.
- Context budgeting and compaction performance-sensitive paths.
- Session save behavior and atomic persistence.
- Tool timeout and interruption behavior.
- Agent turn-loop behavior, including invalid replies and multi-step sessions.
- Any newly introduced instrumentation or configuration.

Where practical, use fake HTTP clients, fake clocks/sleeps, temporary directories, and mocked executors so tests remain deterministic and fast.

## Acceptance criteria

- A documented reproduction or benchmark exists for the original slowness.
- The measured bottleneck is identified in code comments or documentation.
- The fix improves the affected path without changing the public protocol or weakening safety and persistence guarantees.
- Existing tests pass, and regression tests cover the diagnosed failure mode.
- A representative small task completes without unexplained multi-second local overhead apart from measured API/service latency or explicitly requested tool work.
- User-visible progress remains clear during unavoidable API retries, long requests, and tool execution.
- The implementation does not log secrets, full prompts, or sensitive session contents.

## Implementation order for the next agent

1. Read the existing tests for `api.py`, `context.py`, `loop.py`, `session.py`, and `tools.py`.
2. Run the complete test suite and capture the baseline.
3. Add temporary or debug-gated timing measurements and reproduce the issue.
4. Identify the dominant bottleneck from measurements.
5. Implement one focused fix at a time, adding a regression test for each.
6. Run targeted tests, then the full suite.
7. Update user-facing documentation only if behavior or configuration changes.
8. Review the final diff for unnecessary complexity, privacy leaks, and altered safety behavior.
