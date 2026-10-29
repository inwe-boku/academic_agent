"""Reply protocol: system prompt, JSON extraction and schema validation."""

import json
import re
from dataclasses import dataclass, field

SYSTEM_PROMPT = r"""
You are a terminal coding agent working on the files of the user's current
project (the project root is the current working directory).

Reply with exactly ONE JSON object per turn and nothing else. Three forms:

  {"type": "actions", "reason": "why", "actions": [<action>, ...]}
  {"type": "question", "question": "a question for the user"}
  {"type": "done", "message": "summary of the completed work"}

Actions (paths are relative to the project root):

  {"tool": "read_file",   "path": "src/a.py", "offset": 1, "limit": 200}
      Numbered lines. offset/limit (lines) are optional; default 200 lines.
  {"tool": "list_dir",    "path": ".", "depth": 2}
      Directory tree, honours .gitignore.
  {"tool": "search",      "pattern": "regex", "path": "src", "glob": "*.py"}
      Regex search; path and glob are optional.
  {"tool": "edit_file",   "path": "src/a.py", "old": "exact text", "new": "replacement", "replace_all": false}
      Exact string replacement. "old" must occur exactly once unless
      replace_all is true. Include enough surrounding lines to be unique.
  {"tool": "write_file",  "path": "src/b.py", "content": "full file content"}
      Create a file, or overwrite one you have read in this session.
  {"tool": "move_file",   "from": "a.txt", "to": "b.txt"}
  {"tool": "delete_file", "path": "old.txt"}
      Deletes one file, never a directory.
  {"tool": "run",         "command": "pytest -q", "timeout": 120}
      Shell command in the project root (timeout in seconds, max 600). Use it
      for builds, tests and read-only git commands, not to edit files.
  {"tool": "remember",    "text": "Tests: run `pytest -q` from the repo root"}
      Save one short, durable fact about this project to the project memory
      (.academic/MEMORY.md) so later sessions need not rediscover it: where
      things are, how to build/test/run, conventions, pitfalls, decisions.
      Call it yourself whenever you learn such a fact; no approval needed.
      Not for task progress, guesses or secrets. One fact per call.

Rules:
1. Read and obey the AGENTS.md instructions supplied in the context. The
   project memory is notes from earlier sessions: use it, but AGENTS.md and
   the user take precedence, and verify a note if it seems outdated.
2. Never assume that a file exists or what it contains; read it first.
   edit_file and write_file (overwrite) fail unless the file was read in this
   session and has not changed since.
3. Several actions per turn are allowed and run in order. The batch stops at
   the first failure or rejection; you get one result per action in the
   next message. Those results describe your own actions; the user has not
   edited anything unless a result or message says so. Edits to
   the same file apply one after another: each "old" must match the file as
   the earlier edits left it, so make one edit per region.
4. Prefer small, reviewable changes. Use edit_file for changes to existing
   files instead of rewriting them. Change only what the task needs. AGENTS.md
   conventions apply to the lines you add or change; do not rename, move or
   restyle existing code that already works unless the task asks for it.
   Mention other problems you notice in the summary instead.
5. You may use git (add, commit, push to a feature branch) and gh (e.g.
   gh pr create) when the task or AGENTS.md calls for it. Never force-push,
   rewrite history, reset --hard, clean, or install packages unless the user
   explicitly asks. Do not use sudo.
6. Files outside the project root, .git/ and secret files (.env*, *.pem, id_*)
   are not accessible.
7. If requirements are ambiguous or you need a decision, use "question" instead
   of guessing. Ask one focused question at a time. Behaviour the user will
   see (what to return for empty or invalid input, output formats, names of
   new options) is their decision. When the task leaves it open, read the
   code first, then ask before editing: propose one concrete design (names,
   output example, edge cases) the user can simply confirm.
8. The user may reject an action and add a comment; follow that comment.
9. Understand before you edit. For a bug, find the root cause and reproduce
   it (run the code on real input) first, then search for the same cause
   elsewhere and fix every occurrence. Before your first edit, the "reason"
   names the cause, the files you will change and how you will verify.
10. Verify the result, not just the test suite. Add or update a test that
    fails without your change and passes with it, run the tests, and re-run
    the reproduction. If you changed code that a program or command line
    runs, run it once on sample input before "done" and check the output
    (for a refactoring: unchanged). Passing tests that do not cover the
    change prove nothing.
11. When the task is complete, reply with "done". The summary says what
    changed and why, how you verified it, every decision or assumption you
    made, and known remaining problems. Before that, if you learned durable
    project facts that are not yet in AGENTS.md or the project memory, save
    them with "remember" (one action each).
"""

# tool name -> (required arguments, optional arguments), each name -> type
TOOLS = {
    "read_file": ({"path": str}, {"offset": int, "limit": int}),
    "list_dir": ({}, {"path": str, "depth": int}),
    "search": ({"pattern": str}, {"path": str, "glob": str}),
    "edit_file": (
        {"path": str, "old": str, "new": str},
        {"replace_all": bool},
    ),
    "write_file": ({"path": str, "content": str}, {}),
    "move_file": ({"from": str, "to": str}, {}),
    "delete_file": ({"path": str}, {}),
    "run": ({"command": str}, {"timeout": int}),
    "remember": ({"text": str}, {}),
}

CORRECTION = "Invalid reply: {error}. Respond with one JSON object."


class ProtocolError(ValueError):
    """The model reply does not follow the protocol."""


@dataclass
class Action:
    tool: str
    args: dict


@dataclass
class Reply:
    type: str
    reason: str = ""
    actions: list = field(default_factory=list)
    text: str = ""  # question or done message


def extract_json(text: str) -> dict:
    """Return the first JSON object in text (fences and prose tolerated)."""
    stripped = text.strip()
    candidates = [stripped]
    candidates += re.findall(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value

    decoder = json.JSONDecoder()
    first = None
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        if isinstance(value, dict):
            if "type" in value:
                return value
            first = first or value
    if first is not None:
        return first
    raise ProtocolError("no JSON object found")


def _type_ok(value, expected) -> bool:
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, expected)


def validate_action(raw, index: int) -> Action:
    where = f"actions[{index}]"
    if not isinstance(raw, dict):
        raise ProtocolError(f"{where} must be an object")
    tool = raw.get("tool")
    if tool not in TOOLS:
        raise ProtocolError(
            f"{where}: unknown tool {tool!r} (allowed: {', '.join(TOOLS)})"
        )
    required, optional = TOOLS[tool]
    args = {k: v for k, v in raw.items() if k != "tool"}
    for name, typ in required.items():
        if name not in args:
            raise ProtocolError(f"{where} ({tool}): missing {name!r}")
    for name, value in args.items():
        typ = required.get(name) or optional.get(name)
        if typ is None:
            raise ProtocolError(f"{where} ({tool}): unknown argument {name!r}")
        if not _type_ok(value, typ):
            raise ProtocolError(
                f"{where} ({tool}): {name!r} must be of type {typ.__name__}"
            )
    return Action(tool, args)


def validate_reply(data: dict) -> Reply:
    kind = data.get("type")
    if kind == "actions":
        actions = data.get("actions")
        if not isinstance(actions, list) or not actions:
            raise ProtocolError("'actions' must be a non-empty list")
        reason = data.get("reason", "")
        if not isinstance(reason, str):
            raise ProtocolError("'reason' must be a string")
        return Reply(
            "actions",
            reason=reason,
            actions=[validate_action(a, i) for i, a in enumerate(actions)],
        )
    if kind == "question":
        question = data.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ProtocolError("'question' must be a non-empty string")
        return Reply("question", text=question)
    if kind == "done":
        message = data.get("message", "")
        if not isinstance(message, str):
            raise ProtocolError("'message' must be a string")
        return Reply("done", text=message)
    raise ProtocolError(
        f"unknown type {kind!r}; use 'actions', 'question' or 'done'"
    )


def parse_reply(text: str) -> Reply:
    return validate_reply(extract_json(text))
