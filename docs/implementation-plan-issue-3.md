# Implementation Plan: Issue #3 — Make Memory Accessible

## Objective

Add a durable, inspectable memory facility that extracts useful stable information from completed or ongoing chats and makes it available to later sessions, without treating untrusted chat content as executable instructions or silently changing the current session context.

## Current architecture relevant to memory

- `academic_agent/session.py` persists session state and is the natural owner of durable session-adjacent metadata.
- `academic_agent/context.py` manages history budgeting, compaction, summaries, stubs, and truncation.
- `academic_agent/loop.py` controls model turns and tool execution.
- `academic_agent/tools.py` exposes filesystem operations and must not gain an unrestricted memory-writing path without policy checks.
- `docs/spec.md`, `docs/security.md`, and `docs/configuration.md` define the protocol, safety model, and configuration conventions that the feature must preserve.

## Phase 1: Define the memory contract

1. Define the distinction between:
   - session history, which records the current conversation;
   - generated summaries, which support context compaction; and
   - persistent memory, which contains selected information intended for later sessions.
2. Specify a versioned memory record format with at least:
   - stable identifier;
   - content;
   - category or kind;
   - source session identifier;
   - creation and update timestamps;
   - optional confidence or review state;
   - schema version.
3. Define the storage location and configuration, including behavior when the location is unavailable or unwritable.
4. Define retrieval semantics: what is loaded automatically, what is explicitly searched, ordering, limits, and duplicate handling.
5. Define deletion, editing, clearing, and export behavior so users can inspect and control stored information.
6. Document that memory is advisory data, not policy, system instructions, or authorization.

## Phase 2: Design extraction and persistence

1. Add a dedicated memory module rather than embedding memory logic in the turn loop.
2. Implement validated serialization and deserialization with graceful handling of malformed, old, or partially written files.
3. Use atomic writes and preserve the previous valid store if a write fails.
4. Add bounded storage and deterministic ordering to prevent unbounded growth.
5. Implement an explicit extraction workflow, initially requiring the agent or user to request memory updates rather than saving every message automatically.
6. Require confirmation for sensitive, ambiguous, or high-impact facts; never persist secrets, credentials, tokens, private keys, or raw prompts by default.
7. Ensure concurrent sessions cannot silently overwrite each other; use locking or conflict-safe merge behavior where necessary.

## Phase 3: Integrate with sessions and context

1. Add session commands or protocol messages for listing, searching, adding, updating, deleting, and clearing memory.
2. Load only a bounded, relevant memory selection into a new session, clearly marked as untrusted reference material.
3. Keep memory outside the ordinary conversation history unless it is intentionally referenced, preventing repeated duplication during compaction.
4. Expose memory operations through the existing approval and policy mechanisms.
5. Ensure resumed sessions preserve their relationship to memory records without duplicating entries.
6. Provide user-visible feedback whenever memory is read, proposed, saved, rejected, or deleted.

## Phase 4: Regression coverage

Add deterministic tests for:

- record validation, schema versioning, timestamps, and serialization;
- atomic writes and recovery from malformed or interrupted files;
- deduplication, ordering, limits, and concurrent-update behavior;
- secret and sensitive-data filtering;
- explicit confirmation and policy enforcement;
- session creation, resumption, compaction, and bounded context injection;
- memory search, update, deletion, clearing, and export;
- unavailable or read-only storage;
- backward compatibility with sessions created before memory support.

Use temporary directories, fake clocks, and mocked model responses. Tests must not depend on a real user home directory or network service.

## Documentation

Update `docs/spec.md`, `docs/configuration.md`, `docs/security.md`, `docs/usage.md`, and `docs/troubleshooting.md` with the record format, commands, storage behavior, privacy guarantees, and recovery procedures. Include examples that use harmless project facts rather than personal or secret data.

## Acceptance criteria

- A later session can inspect and use explicitly saved facts without repeating the original investigation.
- Users can list, search, review, edit, delete, export, and clear memory.
- Memory is bounded, versioned, atomically persisted, and recoverable after interrupted writes.
- Secrets and sensitive content are not saved automatically.
- Memory cannot bypass tool approvals, safety policy, context limits, or system/developer instructions.
- Existing sessions and protocol clients continue to work when memory is unused.
- Tests cover persistence failures, malformed data, compaction, resumption, and privacy filtering.

## Implementation order for the next agent

1. Read the session, context, loop, protocol, policy, tools, and security documentation and tests.
2. Add the record schema and isolated storage tests.
3. Implement atomic persistence and user-controlled CRUD operations.
4. Integrate bounded retrieval with new-session and resumed-session context construction.
5. Add extraction/confirmation behavior and policy checks.
6. Update documentation and protocol reference.
7. Run targeted tests, then the complete suite and documentation build.
8. Review the final diff for accidental secret retention, prompt injection risks, unbounded context growth, and data-loss paths.
