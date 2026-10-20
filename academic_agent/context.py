"""Initial context, output truncation and the history budget."""

import math
import re
from pathlib import Path

from . import gitutil
from .policy import is_denied_rel
from .protocol import SYSTEM_PROMPT

MAX_OUTPUT_LINES = 200
MAX_OUTPUT_CHARS = 20_000
INITIAL_DEPTH = 3
INITIAL_ENTRIES = 300

BUDGET_RATIO = 0.7
KEEP_TURNS = 6
SUMMARY_MARKER = "\n\n## Summary of earlier work (older turns were compacted)\n"
DEFAULT_CONTEXT_WINDOW = 128_000

SUMMARY_PROMPT = """\
Summarise the following part of a coding-agent session so that it can replace
those turns in the history. Keep it concise but complete:
- the task and any decisions or user instructions,
- files read and changed, with the key facts learned about them,
- the current state of the work,
- open problems and next steps.
Reply with plain text, not JSON."""


def _number(n: int) -> str:
    return f"{n:,}".replace(",", " ")


# ---- Directory listing ----------------------------------------------------

def tree_listing(root, base=None, depth=2, max_entries=1000) -> str:
    """Indented tree of visible files below base, honouring .gitignore."""
    root = Path(root).resolve()
    base = Path(base or root).resolve()
    prefix = base.relative_to(root).parts
    tree: dict = {}
    for rel in gitutil.visible_files(root):
        parts = Path(rel).parts
        if parts[:len(prefix)] != prefix or is_denied_rel(parts):
            continue
        node = tree
        for part in parts[len(prefix):-1]:
            node = node.setdefault(part, {})
        if len(parts) > len(prefix):
            node.setdefault(parts[-1], None)

    def count(node) -> int:
        return sum(1 if v is None else count(v) for v in node.values())

    lines: list[str] = []
    omitted = 0

    def walk(node, level):
        nonlocal omitted
        for name in sorted(node, key=lambda n: (node[n] is None, n)):
            child = node[name]
            if len(lines) >= max_entries:
                omitted += 1 if child is None else count(child)
                continue
            indent = "  " * level
            if child is None:
                lines.append(f"{indent}{name}")
            elif level + 1 >= depth:
                lines.append(f"{indent}{name}/  ({count(child)} files)")
            else:
                lines.append(f"{indent}{name}/")
                walk(child, level + 1)

    walk(tree, 0)
    if omitted:
        lines.append(f"[... {_number(omitted)} more files omitted, use list_dir ...]")
    return "\n".join(lines) if lines else "(empty)"


# ---- AGENTS.md and the first message ---------------------------------------

def find_agents_files(start: Path) -> list[Path]:
    """AGENTS.md files from the filesystem root down to start.

    More-specific files come later and therefore have higher priority.
    """
    start = start.resolve()
    ancestors = list(start.parents)[::-1] + [start]
    return [d / "AGENTS.md" for d in ancestors if (d / "AGENTS.md").is_file()]


def read_agents_files(cwd: Path) -> str:
    files = find_agents_files(cwd)
    if not files:
        return "No AGENTS.md file was found."
    sections = []
    for file in files:
        content = file.read_text(encoding="utf-8", errors="replace")
        sections.append(f"--- {file} ---\n{content}")
    return "\n\n".join(sections)


def build_initial_prompt(root: Path, task: str) -> str:
    """First user message: system prompt plus project context.

    The API only accepts the roles "user" and "assistant", so the system prompt
    is prepended to the first user message.
    """
    tree = tree_listing(root, depth=INITIAL_DEPTH, max_entries=INITIAL_ENTRIES)
    return f"""{SYSTEM_PROMPT.strip()}

Project root (current working directory):
{root}

User task:
{task}

Project file listing (3 levels, .gitignore honoured):
{tree}

AGENTS.md instructions:
{read_agents_files(root)}

Determine the next action."""


# ---- Truncation ------------------------------------------------------------

def _cap_chars(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    omitted = len(text) - 2 * half
    return (f"{text[:half]}\n[... {_number(omitted)} characters omitted, "
            f"use offset/limit ...]\n{text[-half:]}")


def truncate_output(text: str, max_lines=MAX_OUTPUT_LINES,
                    max_chars=MAX_OUTPUT_CHARS) -> str:
    """Keep head and tail of long tool output with a marker in between."""
    lines = text.split("\n")
    if len(lines) > max_lines:
        half = max_lines // 2
        omitted = len(lines) - 2 * half
        text = "\n".join(
            lines[:half]
            + [f"[... {_number(omitted)} lines omitted, use offset/limit ...]"]
            + lines[-half:]
        )
    return _cap_chars(text, max_chars)


# ---- History budget --------------------------------------------------------

def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / 3.5)


def estimate_messages(messages) -> int:
    return sum(estimate_tokens(m["content"]) for m in messages)


class HistoryBudget:
    """Tracks the prompt size and decides when to compact the history."""

    def __init__(self, context_window: int | None, ratio=BUDGET_RATIO):
        self.window = context_window or DEFAULT_CONTEXT_WINDOW
        self.limit = int(self.window * ratio)
        self.last_prompt_tokens: int | None = None
        self.last_len = 0

    def record(self, prompt_tokens: int | None, n_messages: int) -> None:
        if prompt_tokens:
            self.last_prompt_tokens = prompt_tokens
            self.last_len = n_messages

    def reset(self) -> None:
        self.last_prompt_tokens = None
        self.last_len = 0

    def estimate(self, messages) -> int:
        chars_estimate = estimate_messages(messages)
        if self.last_prompt_tokens is None or self.last_len > len(messages):
            return chars_estimate
        return self.last_prompt_tokens + estimate_messages(messages[self.last_len:])

    def over(self, messages) -> bool:
        return self.estimate(messages) > self.limit


def split_for_compaction(messages, keep_turns=KEEP_TURNS):
    """Return (middle, tail) or None if there is nothing to compact.

    The first message is always kept. The tail holds the latest keep_turns
    turns and starts with an assistant message so roles keep alternating.
    """
    n = len(messages)
    cut = max(1, n - 2 * keep_turns)
    while cut < n and messages[cut]["role"] != "assistant":
        cut += 1
    middle = messages[1:cut]
    if not middle:
        return None
    return middle, messages[cut:]


def compaction_request(first: str, middle, task: str, per_message=6000) -> str:
    _, _, previous = first.partition(SUMMARY_MARKER)
    parts = [SUMMARY_PROMPT, f"\nTask:\n{task}"]
    if previous:
        parts.append(f"\nEarlier summary:\n{previous}")
    parts.append("\nTurns to summarise:")
    for m in middle:
        content = _cap_chars(m["content"], per_message)
        parts.append(f"\n--- {m['role']} ---\n{content}")
    return "\n".join(parts)


def apply_summary(messages, summary: str, keep_turns=KEEP_TURNS) -> list:
    """Replace the compacted turns by the summary.

    The summary is attached to the first user message so that user and
    assistant messages keep alternating.
    """
    split = split_for_compaction(messages, keep_turns)
    if split is None:
        return messages
    _, tail = split
    base = messages[0]["content"].partition(SUMMARY_MARKER)[0]
    first = {"role": "user", "content": base + SUMMARY_MARKER + summary.strip()}
    return [first] + tail


_RESULT_HEADER = re.compile(r"^\[(\d+)\] (\S+) (.*?): ", re.MULTILINE)


def stub_result(content: str) -> str | None:
    """One-line stubs for a tool-result message, or None if not one."""
    headers = list(_RESULT_HEADER.finditer(content))
    if not headers or headers[0].start() != 0:
        return None
    stubs = []
    for i, match in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(content)
        header_end = content.find("\n", match.end(), end)
        body = content[header_end + 1:end].strip() if header_end != -1 else ""
        n_lines = body.count("\n") + 1 if body else 0
        stubs.append(f"[{match.group(2)} {match.group(3)}: "
                     f"{n_lines} lines, omitted]")
    return "\n".join(stubs)


def stub_old_results(messages, budget: HistoryBudget, keep_turns=KEEP_TURNS):
    """Fallback compaction: stub old tool results, oldest first."""
    split = split_for_compaction(messages, keep_turns)
    if split is None:
        return messages
    middle, _ = split
    messages = list(messages)
    for i in range(1, 1 + len(middle)):
        if estimate_messages(messages) <= budget.limit:
            break
        m = messages[i]
        if m["role"] != "user":
            continue
        stub = stub_result(m["content"])
        if stub is not None and len(stub) < len(m["content"]):
            messages[i] = {"role": "user", "content": stub}
    return messages
