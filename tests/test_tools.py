import os
import shutil
import signal
import time

import pytest

from academic_agent.policy import Policy
from academic_agent.protocol import Action
from academic_agent.session import Session
from academic_agent.tools import Executor, ToolError


def run(executor, tool, **args):
    return executor.prepare(Action(tool, args)).execute()


def bump(path):
    """Change mtime and size without depending on clock resolution."""
    path.write_text(path.read_text() + "x\n")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))


# ---- read_file ------------------------------------------------------------

def test_read_file_numbers_lines(executor, project):
    (project / "a.py").write_text("x = 1\ny = 2\n")
    result = run(executor, "read_file", path="a.py")
    assert result.ok
    assert result.output.splitlines() == ["    1  x = 1", "    2  y = 2"]


def test_read_file_offset_limit(executor, project):
    (project / "a.txt").write_text("".join(f"line{i}\n" for i in range(1, 11)))
    result = run(executor, "read_file", path="a.txt", offset=3, limit=2)
    assert "    3  line3" in result.output
    assert "    4  line4" in result.output
    assert "line5" not in result.output.split("[")[0]
    assert "6 more lines, use offset=5" in result.output


def test_read_file_errors(executor, project):
    (project / "bin").write_bytes(b"\x00\x01")
    (project / "d").mkdir()
    with pytest.raises(ToolError, match="no such file"):
        run(executor, "read_file", path="missing.txt")
    with pytest.raises(ToolError, match="binary"):
        run(executor, "read_file", path="bin")
    with pytest.raises(ToolError, match="directory"):
        run(executor, "read_file", path="d")


def test_read_file_confined(executor):
    with pytest.raises(ToolError, match="outside"):
        executor.prepare(Action("read_file", {"path": "../x"}))
    with pytest.raises(ToolError, match="not allowed"):
        executor.prepare(Action("read_file", {"path": ".env"}))


# ---- edit_file ------------------------------------------------------------

def test_edit_requires_read(executor, project):
    (project / "a.py").write_text("x = 1\n")
    with pytest.raises(ToolError, match="has not been read"):
        executor.prepare(Action("edit_file", {"path": "a.py", "old": "1", "new": "2"}))


def test_edit_missing_text(executor, project):
    (project / "a.py").write_text("x = 1\n")
    run(executor, "read_file", path="a.py")
    with pytest.raises(ToolError, match="not found"):
        executor.prepare(Action("edit_file", {"path": "a.py", "old": "y", "new": "z"}))


def test_edit_ambiguous(executor, project):
    (project / "a.py").write_text("x = 1\nx = 1\n")
    run(executor, "read_file", path="a.py")
    with pytest.raises(ToolError, match="ambiguous"):
        executor.prepare(Action("edit_file", {"path": "a.py", "old": "x = 1", "new": "x = 2"}))
    result = run(executor, "edit_file", path="a.py", old="x = 1", new="x = 2",
                 replace_all=True)
    assert result.ok
    assert (project / "a.py").read_text() == "x = 2\nx = 2\n"


def test_edit_stale_file(executor, project):
    path = project / "a.py"
    path.write_text("x = 1\n")
    run(executor, "read_file", path="a.py")
    bump(path)
    with pytest.raises(ToolError, match="changed on disk"):
        executor.prepare(Action("edit_file", {"path": "a.py", "old": "1", "new": "2"}))


def test_edit_stale_between_preview_and_execute(executor, project):
    path = project / "a.py"
    path.write_text("x = 1\n")
    run(executor, "read_file", path="a.py")
    prepared = executor.prepare(Action("edit_file", {"path": "a.py", "old": "1", "new": "2"}))
    bump(path)
    with pytest.raises(ToolError, match="changed on disk"):
        prepared.execute()


def test_edit_diff_and_apply(executor, project):
    (project / "a.py").write_text("a\nb\nc\n")
    run(executor, "read_file", path="a.py")
    prepared = executor.prepare(Action("edit_file", {"path": "a.py", "old": "b\n", "new": "B\n"}))
    assert prepared.tier == "write"
    assert prepared.diff.splitlines() == [
        "--- a/a.py", "+++ b/a.py", "@@ -1,3 +1,3 @@", " a", "-b", "+B", " c",
    ]
    assert (project / "a.py").read_text() == "a\nb\nc\n"  # nothing before approval
    assert prepared.execute().ok
    assert (project / "a.py").read_text() == "a\nB\nc\n"
    # a second edit works without re-reading: the agent's own write is known
    assert run(executor, "edit_file", path="a.py", old="a\n", new="A\n").ok
    assert executor.session.touched == {"a.py": {"created": False}}


def test_edit_keeps_crlf(executor, project):
    (project / "w.txt").write_bytes(b"one\r\ntwo\r\n")
    run(executor, "read_file", path="w.txt")
    run(executor, "edit_file", path="w.txt", old="two", new="TWO")
    assert (project / "w.txt").read_bytes() == b"one\r\nTWO\r\n"


# ---- write / move / delete ------------------------------------------------

def test_write_new_file(executor, project):
    prepared = executor.prepare(Action("write_file", {"path": "new/b.py", "content": "hi\n"}))
    assert "+hi" in prepared.diff
    assert prepared.execute().ok
    assert (project / "new" / "b.py").read_text() == "hi\n"
    assert executor.session.touched == {"new/b.py": {"created": True}}


def test_overwrite_requires_read(executor, project):
    (project / "b.py").write_text("old\n")
    with pytest.raises(ToolError, match="has not been read"):
        executor.prepare(Action("write_file", {"path": "b.py", "content": "new\n"}))
    run(executor, "read_file", path="b.py")
    assert run(executor, "write_file", path="b.py", content="new\n").ok
    assert executor.session.touched == {"b.py": {"created": False}}


def test_move_file(executor, project):
    (project / "a.txt").write_text("x")
    assert run(executor, "move_file", **{"from": "a.txt", "to": "sub/b.txt"}).ok
    assert (project / "sub" / "b.txt").read_text() == "x"
    assert executor.session.touched == {
        "a.txt": {"created": False}, "sub/b.txt": {"created": True}}
    (project / "c.txt").write_text("y")
    with pytest.raises(ToolError, match="already exists"):
        executor.prepare(Action("move_file", {"from": "c.txt", "to": "sub/b.txt"}))


def test_delete_file(executor, project):
    (project / "d").mkdir()
    (project / "a.txt").write_text("x\n")
    with pytest.raises(ToolError, match="directory"):
        executor.prepare(Action("delete_file", {"path": "d"}))
    prepared = executor.prepare(Action("delete_file", {"path": "a.txt"}))
    assert "-x" in prepared.diff
    assert prepared.execute().ok
    assert not (project / "a.txt").exists()


def test_delete_created_file_forgets_it(executor, project):
    run(executor, "write_file", path="tmp.txt", content="x")
    run(executor, "delete_file", path="tmp.txt")
    assert executor.session.touched == {}


# ---- list_dir and search --------------------------------------------------

def test_list_dir_honours_gitignore(git_project):
    executor = Executor(Policy(git_project), Session(cwd=str(git_project), task="t"))
    (git_project / "ignored").mkdir()
    (git_project / "ignored" / "x.txt").write_text("x")
    (git_project / "src").mkdir()
    (git_project / "src" / "m.py").write_text("x")
    (git_project / ".env").write_text("SECRET=1")
    out = run(executor, "list_dir").output
    assert out.splitlines() == ["src/", "  m.py", ".gitignore", "a.txt"]
    # gitignored files can still be read explicitly
    assert run(executor, "read_file", path="ignored/x.txt").ok


def test_list_dir_depth(executor, project):
    (project / "a" / "b" / "c").mkdir(parents=True)
    (project / "a" / "b" / "c" / "deep.txt").write_text("x")
    out = run(executor, "list_dir", depth=1).output
    assert out == "a/  (1 files)"


@pytest.mark.parametrize("use_rg", [True, False])
def test_search(executor, project, monkeypatch, use_rg):
    if not use_rg:
        monkeypatch.setattr("academic_agent.tools.shutil.which", lambda _: None)
    (project / "src").mkdir()
    (project / "src" / "m.py").write_text("def foo():\n    return 1\n")
    (project / "notes.md").write_text("foo bar\n")
    (project / ".env").write_text("foo=secret\n")
    out = run(executor, "search", pattern=r"foo\(").output
    assert out.strip() == "src/m.py:1:def foo():"
    out = run(executor, "search", pattern="foo", glob="*.md").output
    assert out.strip() == "notes.md:1:foo bar"
    assert ".env" not in run(executor, "search", pattern="secret").output



@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep not installed")
def test_search_ignores_open_stdin_pipe(executor, project):
    """Non-interactive callers may leave stdin as an open pipe; rg must search
    the project, not wait on stdin."""
    (project / "m.py").write_text("needle\n")
    read_end, write_end = os.pipe()
    saved = os.dup(0)
    os.dup2(read_end, 0)
    signal.alarm(10)  # fail instead of hanging if rg waits on stdin
    try:
        out = run(executor, "search", pattern="needle").output
    finally:
        signal.alarm(0)
        os.dup2(saved, 0)
        for fd in (saved, read_end, write_end):
            os.close(fd)
    assert out.strip() == "m.py:1:needle"


# ---- run ------------------------------------------------------------------

def test_run_in_root_with_scrubbed_env(executor, project, monkeypatch):
    monkeypatch.setenv("ACADEMIC_AI_CLIENT_SECRET", "topsecret")
    monkeypatch.setenv("MY_TOKEN", "abc")
    result = run(executor, "run", command="pwd; env")
    assert result.ok and result.exit_code == 0
    assert str(project) in result.output
    assert "topsecret" not in result.output and "MY_TOKEN" not in result.output
    assert executor.session.run_log == [{"command": "pwd; env", "exit_code": 0}]


def test_run_failure_and_timeout(executor):
    result = run(executor, "run", command="exit 3")
    assert not result.ok and result.exit_code == 3
    assert result.status == "FAILED (exit code 3)"
    start = time.monotonic()
    result = run(executor, "run", command="sleep 5", timeout=1)
    assert time.monotonic() - start < 4
    assert result.exit_code == 124 and "Timed out" in result.output


def test_run_flags_dangerous(executor):
    prepared = executor.prepare(Action("run", {"command": "rm -rf x"}))
    assert prepared.tier == "exec" and prepared.dangerous
