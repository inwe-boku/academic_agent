"""Project memory: durable notes in .academic/MEMORY.md, kept out of git."""

import datetime
import os
import re
from pathlib import Path

from . import gitutil
from .session import redact

MEMORY_DIR = ".academic"
MEMORY_FILE = "MEMORY.md"
MAX_ENTRY_CHARS = 1_000
MAX_FILE_CHARS = 16_000    # oldest entries are dropped beyond this
MAX_PROMPT_CHARS = 8_000   # injected into the first message

HEADER = """# Project memory

Notes saved by Academic Agent sessions for later sessions in this project.
Edit or delete entries freely; this folder is listed in .gitignore.

"""

_DATE_SUFFIX = re.compile(r"\s+\(\d{4}-\d{2}-\d{2}\)$")


class MemoryRejected(Exception):
    """An entry cannot be saved; reported back to the model."""


def memory_rel() -> str:
    return f"{MEMORY_DIR}/{MEMORY_FILE}"


def memory_path(root) -> Path:
    return Path(root) / MEMORY_DIR / MEMORY_FILE


def load(root, max_chars=MAX_PROMPT_CHARS) -> str:
    """The notes for the first message; newest entries win when too long."""
    try:
        text = memory_path(root).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    tail = text[-max_chars:]
    tail = tail[tail.find("\n") + 1:]
    return (f"[... older notes omitted; read {memory_rel()} for all of them ...]\n"
            + tail)


def _normalize(entry: str) -> str:
    return " ".join(_DATE_SUFFIX.sub("", entry).split()).casefold()


def _entry_text(text: str, secrets) -> str:
    text = " ".join(text.split())
    if not text:
        raise MemoryRejected("empty note")
    if len(text) > MAX_ENTRY_CHARS:
        raise MemoryRejected(f"note too long ({len(text)} characters, at most "
                             f"{MAX_ENTRY_CHARS}); keep it short")
    if redact(text, secrets) != text:
        raise MemoryRejected("note looks like it contains a secret; not saved")
    return text


def append(root, text: str, secrets=(), today=None) -> str:
    """Add one note. Returns "saved", "duplicate" or "saved, N old notes
    dropped". Raises MemoryRejected for notes that must not be saved."""
    text = _entry_text(text, secrets)
    path = memory_path(root)
    try:
        current = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = HEADER
    lines = current.rstrip("\n").split("\n")
    entries = [i for i, line in enumerate(lines) if line.startswith("- ")]
    key = _normalize(text)
    if any(_normalize(lines[i][2:]) == key for i in entries):
        return "duplicate"

    date = (today or datetime.date.today()).isoformat()
    if not entries and lines[-1].strip():
        lines.append("")
    lines.append(f"- {text}  ({date})")
    dropped = 0
    while sum(len(l) + 1 for l in lines) > MAX_FILE_CHARS and entries:
        del lines[entries.pop(0) - dropped]
        dropped += 1

    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    if dropped:
        return (f"saved; {dropped} oldest notes dropped (file limit). "
                f"Consider consolidating {memory_rel()}.")
    return "saved"


def ensure_gitignored(root) -> bool:
    """Add the memory folder to root/.gitignore once. Returns True if the
    file was changed."""
    root = Path(root)
    if not gitutil.is_repo(root):
        return False
    gitignore = root / ".gitignore"
    try:
        content = gitignore.read_text(encoding="utf-8")
    except FileNotFoundError:
        content = ""
    patterns = {MEMORY_DIR, f"{MEMORY_DIR}/", f"/{MEMORY_DIR}", f"/{MEMORY_DIR}/"}
    if any(line.strip() in patterns for line in content.splitlines()):
        return False
    if content and not content.endswith("\n"):
        content += "\n"
    gitignore.write_text(content + f"{MEMORY_DIR}/\n", encoding="utf-8")
    return True
