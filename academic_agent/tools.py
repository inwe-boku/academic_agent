"""File tools and the shell tool. All paths go through the Policy."""

import difflib
import os
import re
import shutil
import signal
import subprocess
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable

from . import gitutil
from .context import tree_listing
from .policy import TIERS, Policy, PolicyError, dangerous_reason, is_denied_rel, scrubbed_env
from .protocol import Action
from .session import Session

DEFAULT_READ_LIMIT = 200
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 600
MAX_SEARCH_MATCHES = 500
MAX_SEARCH_FILE_SIZE = 2_000_000


class ToolError(Exception):
    """An action cannot be carried out; reported back without approval."""


@dataclass
class ToolResult:
    ok: bool
    output: str = ""
    status: str = ""  # overrides the default OK/FAILED label
    exit_code: int | None = None
    interrupted: bool = False


@dataclass
class Prepared:
    action: Action
    tier: str
    target: str            # short description: path, command, pattern
    execute: Callable[[], ToolResult]
    diff: str = ""
    dangerous: str | None = None  # reason, for run only


def describe(action: Action) -> str:
    a = action.args
    if action.tool == "run":
        first = a["command"].strip().splitlines()[0] if a["command"].strip() else ""
        return first[:80] + ("…" if len(first) > 80 or "\n" in a["command"].strip() else "")
    if action.tool == "search":
        return repr(a["pattern"]) + (f" in {a['path']}" if a.get("path") else "")
    if action.tool == "move_file":
        return f"{a['from']} -> {a['to']}"
    return a.get("path", ".")


def unified_diff(old: str, new: str, rel: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{rel}", tofile=f"b/{rel}",
    )
    return "".join(l if l.endswith("\n") else l + "\n\\ No newline at end of file\n"
                   for l in lines)


def _stamp(path: Path) -> tuple[int, int]:
    st = path.stat()
    return st.st_mtime_ns, st.st_size


def _read_text(path: Path, rel: str) -> str:
    if not path.exists():
        raise ToolError(f"{rel}: no such file")
    if path.is_dir():
        raise ToolError(f"{rel}: is a directory")
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        raise ToolError(f"{rel}: binary file")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ToolError(f"{rel}: not valid UTF-8 text") from None


class Executor:
    def __init__(self, policy: Policy, session: Session):
        self.policy = policy
        self.root = policy.root
        self.session = session
        self._read: dict[str, tuple[int, int]] = {}

    # -- bookkeeping --

    def _resolve(self, path: str) -> tuple[Path, str]:
        try:
            resolved = self.policy.resolve(path)
        except PolicyError as exc:
            raise ToolError(str(exc)) from None
        return resolved, self.policy.rel(resolved)

    def _remember(self, path: Path, rel: str) -> None:
        self._read[rel] = _stamp(path)

    def _require_fresh(self, path: Path, rel: str) -> None:
        if rel not in self._read:
            raise ToolError(f"{rel} has not been read in this session; "
                            "use read_file first")
        if not path.exists() or _stamp(path) != self._read[rel]:
            raise ToolError(f"{rel} changed on disk since it was read; "
                            "read it again")

    def _touch(self, rel: str, created: bool) -> None:
        self.session.touched.setdefault(rel, {"created": created})

    # -- dispatch --

    def prepare(self, action: Action) -> Prepared:
        """Validate an action and compute its preview. Raises ToolError."""
        handler = getattr(self, f"_prep_{action.tool}")
        return handler(action)

    # -- read tier --

    def _prep_read_file(self, action):
        path, rel = self._resolve(action.args["path"])
        offset = max(1, action.args.get("offset", 1))
        limit = max(1, action.args.get("limit", DEFAULT_READ_LIMIT))

        def execute():
            stamp = _stamp(path) if path.exists() else None
            text = _read_text(path, rel)
            lines = text.splitlines()
            chunk = lines[offset - 1:offset - 1 + limit]
            out = [f"{n:>5}  {line}" for n, line in enumerate(chunk, offset)]
            rest = len(lines) - (offset - 1 + len(chunk))
            if rest > 0:
                out.append(f"[... {rest} more lines, use offset="
                           f"{offset + len(chunk)} ...]")
            if not lines:
                out.append("(empty file)")
            self._read[rel] = stamp
            return ToolResult(True, "\n".join(out))

        return Prepared(action, "read", rel, execute)

    def _prep_list_dir(self, action):
        path, rel = self._resolve(action.args.get("path", "."))
        depth = min(max(1, action.args.get("depth", 2)), 10)

        def execute():
            if not path.is_dir():
                raise ToolError(f"{rel}: not a directory")
            return ToolResult(True, tree_listing(self.root, path, depth=depth))

        return Prepared(action, "read", rel, execute)

    def _prep_search(self, action):
        pattern = action.args["pattern"]
        path, rel = self._resolve(action.args.get("path", "."))
        glob = action.args.get("glob")

        def execute():
            rg = shutil.which("rg")
            output = (self._search_rg(rg, pattern, path, rel, glob) if rg
                      else self._search_python(pattern, path, glob))
            return ToolResult(True, output or "no matches")

        return Prepared(action, "read", describe(action), execute)

    def _search_rg(self, rg, pattern, path, rel, glob):
        cmd = [rg, "--line-number", "--no-heading", "--color", "never",
               "--no-require-git", "--max-columns", "300"]
        for secret in (".env*", "*.pem", "id_*"):
            cmd += ["--glob", f"!{secret}"]
        if glob:
            cmd += ["--glob", glob]
        cmd += ["-e", pattern]
        if rel != ".":
            cmd += ["--", rel]
        proc = subprocess.run(cmd, cwd=self.root, capture_output=True,
                              text=True, errors="replace")
        if proc.returncode == 2 and not proc.stdout:
            raise ToolError(proc.stderr.strip() or "search failed")
        return proc.stdout.rstrip("\n")

    def _search_python(self, pattern, path, glob):
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            raise ToolError(f"invalid regex: {exc}") from None
        base = path.relative_to(self.root).parts
        matches = []
        for rel in gitutil.visible_files(self.root):
            parts = Path(rel).parts
            if parts[:len(base)] != base or is_denied_rel(parts):
                continue
            if glob and not (fnmatch(rel, glob) or fnmatch(parts[-1], glob)):
                continue
            file = self.root / rel
            if path.is_file() and file != path:
                continue
            try:
                if file.stat().st_size > MAX_SEARCH_FILE_SIZE:
                    continue
                text = file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    matches.append(f"{rel}:{n}:{line[:300]}")
                    if len(matches) >= MAX_SEARCH_MATCHES:
                        return "\n".join(matches) + "\n[... match limit reached ...]"
        return "\n".join(matches)

    # -- write tier --

    def _prep_edit_file(self, action):
        a = action.args
        path, rel = self._resolve(a["path"])
        self._require_fresh(path, rel)
        old_text = _read_text(path, rel)
        if not a["old"]:
            raise ToolError("'old' must not be empty")
        count = old_text.count(a["old"])
        if count == 0:
            raise ToolError(f"{rel}: 'old' text not found")
        if count > 1 and not a.get("replace_all"):
            raise ToolError(f"{rel}: 'old' text is ambiguous ({count} matches); "
                            "add surrounding context or set replace_all")
        new_text = old_text.replace(a["old"], a["new"])
        if new_text == old_text:
            raise ToolError(f"{rel}: edit changes nothing")

        def execute():
            self._require_fresh(path, rel)
            path.write_bytes(new_text.encode("utf-8"))
            self._touch(rel, created=False)
            self._remember(path, rel)
            n = count if a.get("replace_all") else 1
            return ToolResult(True, f"{n} replacement(s)")

        return Prepared(action, "write", rel, execute,
                        diff=unified_diff(old_text, new_text, rel))

    def _prep_write_file(self, action):
        path, rel = self._resolve(action.args["path"])
        content = action.args["content"]
        exists = path.exists()
        if exists:
            self._require_fresh(path, rel)
            old_text = _read_text(path, rel)
        else:
            old_text = ""

        def execute():
            if exists:
                self._require_fresh(path, rel)
            elif path.exists():
                raise ToolError(f"{rel} was created meanwhile; read it first")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
            self._touch(rel, created=not exists)
            self._remember(path, rel)
            verb = "overwritten" if exists else "created"
            return ToolResult(True, f"{verb} ({len(content.splitlines())} lines)")

        return Prepared(action, "write", rel, execute,
                        diff=unified_diff(old_text, content, rel))

    def _prep_move_file(self, action):
        src, src_rel = self._resolve(action.args["from"])
        dst, dst_rel = self._resolve(action.args["to"])
        if not src.is_file():
            raise ToolError(f"{src_rel}: no such file")
        if dst.exists():
            raise ToolError(f"{dst_rel} already exists")

        def execute():
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.rename(src, dst)
            self._touch(src_rel, created=False)
            self._touch(dst_rel, created=True)
            if src_rel in self._read:
                self._read[dst_rel] = self._read.pop(src_rel)
            return ToolResult(True, f"moved to {dst_rel}")

        return Prepared(action, "write", f"{src_rel} -> {dst_rel}", execute,
                        diff=f"rename {src_rel} -> {dst_rel}\n")

    def _prep_delete_file(self, action):
        path, rel = self._resolve(action.args["path"])
        if path.is_dir():
            raise ToolError(f"{rel}: is a directory (only files can be deleted)")
        if not path.exists():
            raise ToolError(f"{rel}: no such file")
        try:
            preview = unified_diff(_read_text(path, rel), "", rel)
        except ToolError:
            preview = f"delete {rel} (binary or non-UTF-8)\n"

        def execute():
            path.unlink()
            entry = self.session.touched.get(rel)
            if entry and entry.get("created"):
                del self.session.touched[rel]
            else:
                self._touch(rel, created=False)
            self._read.pop(rel, None)
            return ToolResult(True, "deleted")

        return Prepared(action, "write", rel, execute, diff=preview)

    # -- exec tier --

    def _prep_run(self, action):
        command = action.args["command"]
        if not command.strip():
            raise ToolError("empty command")
        timeout = min(max(1, action.args.get("timeout", DEFAULT_TIMEOUT)),
                      MAX_TIMEOUT)

        def execute():
            result = self.run_command(command, timeout)
            self.session.run_log.append(
                {"command": command, "exit_code": result.exit_code})
            return result

        return Prepared(action, TIERS["run"], describe(action), execute,
                        dangerous=dangerous_reason(command, self.root))

    def run_command(self, command: str, timeout: int) -> ToolResult:
        proc = subprocess.Popen(
            command, shell=True, cwd=self.root, env=scrubbed_env(),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=True,
            text=True, errors="replace",
        )
        try:
            output, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            output, _ = proc.communicate()
            return ToolResult(False, f"{output}\nTimed out after {timeout} s.",
                              status=f"TIMEOUT after {timeout} s", exit_code=124)
        except KeyboardInterrupt:
            _kill_group(proc)
            output, _ = proc.communicate()
            return ToolResult(False, f"{output}\nInterrupted by the user (Ctrl+C).",
                              status="INTERRUPTED by user", exit_code=130,
                              interrupted=True)
        code = proc.returncode
        status = "OK" if code == 0 else f"FAILED (exit code {code})"
        return ToolResult(code == 0, f"exit code: {code}\n{output.rstrip()}",
                          status=status, exit_code=code)


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
