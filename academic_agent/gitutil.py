"""Small git helpers for listings, /diff and /undo."""

import os
import subprocess
from pathlib import Path

DEFAULT_IGNORED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".cache",
}


def _git(root, *args, check=False) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", LC_ALL="C")
    return subprocess.run(
        ["git", *args], cwd=root, env=env, capture_output=True, check=check,
    )


def is_repo(root) -> bool:
    try:
        result = _git(root, "rev-parse", "--is-inside-work-tree")
    except OSError:
        return False
    return result.returncode == 0 and result.stdout.strip() == b"true"


def head(root) -> str | None:
    result = _git(root, "rev-parse", "--verify", "-q", "HEAD")
    return result.stdout.decode().strip() or None if result.returncode == 0 else None


def toplevel(root) -> Path:
    result = _git(root, "rev-parse", "--show-toplevel", check=True)
    return Path(result.stdout.decode().strip()).resolve()


def dirty_files(root) -> set[str]:
    """Modified, staged or untracked files below root, relative to root."""
    root = Path(root).resolve()
    top = toplevel(root)
    out = _git(root, "status", "--porcelain", "-z", "--untracked-files=all",
               check=True).stdout.decode(errors="surrogateescape")
    entries = out.split("\0")
    result = set()
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        paths = [path]
        if "R" in status or "C" in status:
            paths.append(entries[i])  # rename source
            i += 1
        for p in paths:
            absolute = top / p
            try:
                result.add(absolute.relative_to(root).as_posix())
            except ValueError:
                pass
    return result


def visible_files(root) -> list[str]:
    """Files below root honouring .gitignore (relative posix paths)."""
    root = Path(root).resolve()
    if is_repo(root):
        out = _git(root, "ls-files", "-z", "--cached", "--others",
                   "--exclude-standard").stdout.decode(errors="surrogateescape")
        files = {p.rstrip("/") for p in out.split("\0") if p}
        return sorted(p for p in files if (root / p).exists())
    files = []
    for current, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in DEFAULT_IGNORED_DIRS)
        base = Path(current).relative_to(root)
        files.extend((base / n).as_posix() for n in sorted(names))
    return files


def tracked_at(root, commit: str, paths) -> set[str]:
    """Subset of paths (relative to root) that exist in commit."""
    paths = list(paths)
    if not commit or not paths:
        return set()
    out = _git(root, "ls-tree", "-r", "--name-only", "-z", commit, "--",
               *paths).stdout.decode(errors="surrogateescape")
    return {p for p in out.split("\0") if p}


def diff(root, commit: str | None, paths) -> str:
    paths = list(paths)
    if not paths:
        return ""
    args = ["diff", "--no-color"] + ([commit] if commit else []) + ["--", *paths]
    return _git(root, *args).stdout.decode(errors="replace")


def diff_new_file(root, path: str) -> str:
    return _git(root, "diff", "--no-color", "--no-index", "--", "/dev/null",
                path).stdout.decode(errors="replace")


def restore(root, commit: str, paths) -> subprocess.CompletedProcess:
    """Restore paths in the working tree only (the index is left alone)."""
    return _git(root, "restore", f"--source={commit}", "--worktree", "--",
                *paths)


def status_short(root, paths) -> str:
    paths = list(paths)
    if not paths:
        return ""
    return _git(root, "status", "--short", "--untracked-files=all", "--",
                *paths).stdout.decode(errors="replace")
