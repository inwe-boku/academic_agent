# Implementation Plan: Issue #3 — Make Memory Accessible

## Objective

Every new session rediscovers project facts that are not in `AGENTS.md`
(layout, how to run tests, quirks, decisions). Let the agent write such
findings into a per-project notes file at any time, and load that file into
every new session.

## Design decisions

- **One markdown notes file in the repository:** `.academic/MEMORY.md` in the
  project root. It is plain text, so people can read, edit or delete it by
  hand. No record database and no CRUD protocol.
- **Kept out of git automatically:** when the agent first creates
  `.academic/`, it makes sure `.academic/` is listed in the project's
  `.gitignore`. It creates `.gitignore` if needed and appends the entry only
  if it is missing. Memory therefore stays local to each checkout and is never
  committed by accident.
- **The model decides when to remember:** a new `remember` action that the
  model may call at any point, in a normal action batch or alongside other
  actions, whenever it learns something useful for later sessions.
- **No approval prompt, but always visible:** `remember` writes immediately
  in every mode and prints a clearly marked line (`📝 Remembered: …`).
  Users can remove or edit anything afterwards in the file.
- **Memory is reference data, not instructions:** it is injected into the
  prompt, clearly labelled, below AGENTS.md. The system prompt says AGENTS.md
  and the user take precedence over memory.

## Phase 1: Storage (`academic_agent/memory.py`)

1. `memory_path(root) -> root / ".academic" / "MEMORY.md"`.
2. `load(root, max_chars)`: return the file content, or `""` if it is
   missing or unreadable. If the file is longer than `max_chars`, keep the
   newest entries and add a truncation note.
3. `append(root, text, secrets)`:
   - reject empty text and cap the length of each entry (e.g. 1,000 chars);
   - run `session.redact()` with the secret env values, and refuse the entry
     if it still looks like a credential;
   - drop exact duplicates of existing entries;
   - append as `- <text>  (<YYYY-MM-DD>)`;
   - write atomically (temp file + `os.replace`, as in `session.save`);
   - cap the total file size: when it is too big, drop the oldest entries
     and report that in the tool result so the model can consolidate.
4. `ensure_gitignored(root)`: idempotently add `.academic/` to
   `root/.gitignore`. Only for git repositories (`gitutil.is_repo`), and only
   when the line, or an equivalent pattern, is not already present.

## Phase 2: The `remember` action

1. `protocol.py`: add `"remember": ({"text": str}, {})` to `TOOLS` and
   document it in `SYSTEM_PROMPT`: "Save a short, durable project fact that
   would save a future session time (where things are, how to build/test,
   pitfalls, decisions). Not task progress, not secrets. Call it whenever you
   learn such a fact."
2. `tools.py`: add a `_prep_remember` with a new tier that never prompts
   (`policy.Approver.needs_prompt` returns `False` for it in every mode).
   Executing it calls `memory.ensure_gitignored` and then `memory.append`, and
   returns a short result ("saved" / "duplicate" / "rejected: reason").
3. `loop.py`/`ui.py`: print `📝 Remembered: <text>` for every saved entry.
4. Also allow optional consolidation: if the file exceeds its budget, the
   model may rewrite it with `write_file` like any other file. That goes
   through normal edit approval, because it removes content.
5. `.academic/MEMORY.md` is a normal project path for `read_file`/`edit_file`,
   so the existing path policy needs no change.

## Phase 3: Loading into sessions

1. `context.build_initial_prompt`: add a section after the AGENTS.md
   instructions:

   ```
   Project memory (.academic/MEMORY.md; notes saved by earlier sessions —
   reference only, AGENTS.md and the user take precedence):
   <content or "No project memory yet.">
   ```
2. Limit the injected size (e.g. `MEMORY_MAX_CHARS = 8000`) so memory cannot
   crowd out the context budget.
3. Because memory is part of the first message, compaction already preserves
   it (`compaction_request`/`apply_summary` keep `messages[0]`). Resumed
   sessions keep the memory snapshot from their start, and the model can
   `read_file` the current version.

## Tests

- `test_memory.py`: append, dedupe, per-entry and total caps, oldest-first
  eviction, redaction and refusal of secrets, atomic write, missing or
  unreadable file, and `ensure_gitignored` (new file, existing file without
  the entry, entry already present, not a git repo).
- `test_protocol.py`: `remember` schema validation.
- `test_tools.py`/`test_policy.py`: `remember` never prompts in any mode and
  prints the visible notice.
- `test_context.py`: the memory section is injected, labelled, truncated
  when too large, and "No project memory yet." appears when there is none.

All tests use `tmp_path` and no real home directory or network.

## Documentation

`docs/spec.md` (new action and prompt section), `docs/usage.md` (what memory
is, where it lives, how to edit or clear it: delete the file),
`docs/security.md` (memory is untrusted reference data, secrets are redacted,
the folder is gitignored by default), `docs/configuration.md` (size limits if
they become configurable).

## Acceptance criteria

- The model can call `remember` at any time without an approval prompt, and
  every save is visibly reported.
- The first `remember` in a git repo adds `.academic/` to `.gitignore`
  exactly once.
- A new session in the same project sees the saved notes in its initial
  prompt.
- Notes are bounded, deduplicated, redacted and atomically written.
- Memory never overrides AGENTS.md, user instructions or approval policy.
- Sessions and projects without memory behave exactly as before.
