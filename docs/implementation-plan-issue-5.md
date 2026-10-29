# Implementation Plan: Issue #5 — Let Claude Code Use Academic Agent

## Objective

Provide a safe, documented integration that allows Claude Code to invoke Academic Agent as a subtask or external worker, then exercise that integration heavily with automated tests and representative scenarios so implementation defects become actionable issues.

## Integration questions to resolve first

1. Determine which Claude Code integration surface is appropriate and supported by the project: shell/CLI invocation, an MCP server, a Claude Code skill or subagent wrapper, or a combination.
2. Define the stable command and machine-readable protocol boundary. Prefer the existing Academic Agent protocol rather than scraping terminal UI output.
3. Define how prompts, working directories, session identifiers, environment variables, approvals, timeouts, exit codes, and streamed progress are passed.
4. Decide whether Claude Code may invoke nested tools through Academic Agent and document the resulting trust boundary.
5. Define offline test behavior so CI does not require Claude credentials, a live model, or a locally installed Claude Code binary.

## Phase 1: Inspect and specify the adapter

1. Read `docs/spec.md`, `docs/agent-setup-prompt.md`, `docs/development.md`, `academic_agent/__main__.py`, `academic_agent/protocol.py`, `academic_agent/api.py`, `academic_agent/policy.py`, and the relevant tests.
2. Record the current CLI invocation, input/output protocol, exit status behavior, session-resume behavior, and configuration requirements.
3. Specify an adapter contract containing:
   - command and arguments;
   - structured request and response format;
   - stdout/stderr ownership;
   - cancellation and timeout behavior;
   - error categories and exit codes;
   - approval handling;
   - session cleanup and persistence;
   - redaction rules.
4. Keep the adapter narrowly scoped: it must not weaken Academic Agent's existing policy or grant Claude Code implicit approval for destructive actions.

## Phase 2: Implement the Claude Code integration

1. Add the smallest supported integration artifact, such as a documented wrapper command or adapter module, using existing entry points where possible.
2. Make structured output deterministic and keep diagnostics on stderr so callers can parse stdout safely.
3. Forward cancellation and enforce bounded timeouts at every layer; terminate child processes and clean up descendants when required.
4. Preserve approval prompts and expose them in a form Claude Code can handle without auto-approving risky operations.
5. Pass only an allowlisted environment and working-directory configuration. Do not forward API keys or unrelated host secrets by default.
6. Support session IDs and resume behavior explicitly, including cleanup of failed or abandoned invocations.
7. Add clear installation and invocation instructions, with a no-network smoke-test mode for development.

## Phase 3: Build a stress and compatibility harness

1. Add fake API and tool backends so nested-agent behavior can be tested deterministically.
2. Cover single calls, multiple sequential subtasks, concurrent calls if supported, long outputs, malformed model responses, tool approval requests, retries, API failures, cancellation, timeouts, and resumed sessions.
3. Test protocol framing and output separation, including Unicode, multiline output, large payloads, nonzero exit codes, and interrupted streams.
4. Run scenario tests that have Claude Code act as the caller and Academic Agent as the worker, but make the Claude Code executable configurable and optional in CI.
5. Capture bounded diagnostics: scenario name, duration, exit status, step count, and failure category. Do not record prompts, credentials, full transcripts, or sensitive tool output.
6. Add a manual integration test document for environments where Claude Code and valid credentials are available.

## Phase 4: Security and operational review

1. Threat-model prompt injection across the Claude Code to Academic Agent boundary.
2. Verify that caller-provided text cannot alter system/developer policy, approval requirements, storage paths, or allowed tools.
3. Prevent path traversal and unsafe inherited environment configuration.
4. Verify that nested invocations cannot create uncontrolled recursion, process explosions, or unbounded output/storage.
5. Document authentication, rate limits, costs, network requirements, and failure recovery.
6. Confirm that logs and persisted sessions do not expose secrets or full sensitive conversations.

## Regression coverage

Add tests for:

- CLI or adapter request/response framing;
- successful completion and structured failures;
- exit codes and stderr/stdout separation;
- timeout, cancellation, child-process cleanup, and retry behavior;
- approval preservation and policy denial;
- environment and working-directory allowlists;
- session creation, resume, and cleanup;
- malformed, oversized, and interrupted messages;
- concurrent or repeated invocations and recursion limits;
- fake Claude Code end-to-end scenarios;
- existing direct Academic Agent usage to prove no regression.

## Documentation

Update `docs/getting-started.md`, `docs/usage.md`, `docs/development.md`, `docs/security.md`, and `docs/api-reference.md`. Include prerequisites, installation, an example invocation, protocol details, supported limitations, approval behavior, troubleshooting, and the distinction between offline tests and live Claude Code tests.

## Acceptance criteria

- Claude Code can invoke Academic Agent through a documented, repeatable interface.
- The integration uses structured I/O and preserves existing approvals, safety policy, session persistence, and context limits.
- Automated tests exercise normal, failure, stress, cancellation, and security-sensitive paths without network access.
- A live/manual test procedure is available for environments with Claude Code installed.
- Timeouts, recursion, output size, environment inheritance, and process cleanup are bounded.
- CI remains deterministic and does not require Claude credentials.
- Diagnostics are useful while excluding secrets, full prompts, and sensitive transcripts.

## Implementation order for the next agent

1. Inspect the current CLI and protocol and choose the narrowest integration surface.
2. Write the adapter contract and add fake caller/backend fixtures.
3. Implement the wrapper or adapter with timeout, cancellation, framing, and policy preservation.
4. Add unit, integration, and stress tests for deterministic scenarios.
5. Perform the security review and add limits for recursion, output, environment, and processes.
6. Document installation, invocation, manual live testing, and troubleshooting.
7. Run the full test suite and documentation build, then review the diff for accidental trust-boundary changes.
