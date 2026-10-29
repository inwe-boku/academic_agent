"""Session persistence and redaction of secrets."""

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / "academic-agent"


@dataclass
class Session:
    cwd: str
    task: str
    messages: list = field(default_factory=list)
    # relative path -> {"created": bool}
    touched: dict = field(default_factory=dict)
    # relative path -> [mtime_ns, size] when the model last read or wrote it,
    # so edits after --resume still pass the freshness check
    read_stamps: dict = field(default_factory=dict)
    start_commit: str | None = None
    dirty_at_start: list = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float | None = 0.0
    summaries: list = field(default_factory=list)
    run_log: list = field(default_factory=list)
    # One entry per step: seconds and counts only, never message text.
    timings: list = field(default_factory=list)
    # --json runs: the dangerous command that stopped the run, and the one
    # the caller approved with --resume --approve-blocked (used once).
    blocked_command: str | None = None
    approved_command: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def session_path(cwd) -> Path:
    digest = hashlib.sha256(str(cwd).encode()).hexdigest()[:16]
    return state_dir() / f"{digest}.json"


def _ensure_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def save(session: Session) -> None:
    """Atomically write the session (directory 700, file 600)."""
    path = session_path(session.cwd)
    _ensure_dir(path.parent)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(asdict(session), fh)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load(cwd) -> Session | None:
    try:
        data = json.loads(session_path(cwd).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "task" not in data:
        return None
    return Session.from_dict(data)


def clear(cwd) -> bool:
    path = session_path(cwd)
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


def list_sessions() -> list[dict]:
    result = []
    directory = state_dir()
    if not directory.is_dir():
        return result
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        result.append({
            "cwd": data.get("cwd", "?"),
            "task": data.get("task", ""),
            "mtime": time.strftime("%Y-%m-%d %H:%M",
                                   time.localtime(path.stat().st_mtime)),
            "path": path,
        })
    return result


# ---- Redaction -------------------------------------------------------------

_SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z0-9 ]*KEY-----.*?(?:-----END [A-Z0-9 ]*KEY-----|\Z)",
                re.DOTALL), "[REDACTED PRIVATE KEY]"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "[REDACTED]"),
]


def redact(text: str, secret_values=()) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    for value in sorted(set(secret_values), key=len, reverse=True):
        if value:
            text = text.replace(value, "[REDACTED]")
    return text
