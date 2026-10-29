import datetime

import pytest

from academic_agent import memory
from academic_agent.context import build_initial_prompt
from academic_agent.policy import ACCEPT_EDITS, AUTO, DEFAULT, Approver
from academic_agent.protocol import Action, ProtocolError, validate_action
from academic_agent.tools import ToolError

DAY = datetime.date(2026, 10, 29)


def entries(root):
    return [l for l in memory.memory_path(root).read_text().splitlines()
            if l.startswith("- ")]


# ---- storage ---------------------------------------------------------------

def test_append_creates_file_with_header_and_dated_entry(project):
    assert memory.append(project, "Tests:  run\n`pytest -q`", today=DAY) == "saved"
    text = memory.memory_path(project).read_text()
    assert text.startswith("# Project memory")
    assert text.endswith(".gitignore.\n\n- Tests: run `pytest -q`  (2026-10-29)\n")
    assert entries(project) == ["- Tests: run `pytest -q`  (2026-10-29)"]
    assert not list((project / ".academic").glob("*.tmp"))


def test_duplicates_ignored_case_and_whitespace(project):
    memory.append(project, "Docs are built with mkdocs", today=DAY)
    later = datetime.date(2026, 11, 2)
    assert memory.append(project, "docs are  built with MKDOCS", today=later) == "duplicate"
    assert len(entries(project)) == 1


@pytest.mark.parametrize("text, reason", [
    ("   ", "empty"),
    ("x" * (memory.MAX_ENTRY_CHARS + 1), "too long"),
    ("API key is sk-abcdefghijklmnopqrstuvwx", "secret"),
    ("Use header Bearer abcdefghijkl", "secret"),
    ("client secret is hunter2-secret-value", "secret"),
])
def test_rejected_notes(project, text, reason):
    with pytest.raises(memory.MemoryRejected, match=reason):
        memory.append(project, text, secrets=["hunter2-secret-value"])
    assert not memory.memory_path(project).exists()


def test_oldest_entries_dropped_beyond_file_limit(project, monkeypatch):
    monkeypatch.setattr(memory, "MAX_FILE_CHARS", 400)
    for i in range(10):
        status = memory.append(project, f"fact number {i} " + "x" * 40, today=DAY)
    assert "oldest notes dropped" in status
    kept = entries(project)
    assert kept[-1].startswith("- fact number 9 ")
    assert not any(e.startswith("- fact number 0 ") for e in kept)
    assert len(memory.memory_path(project).read_text()) <= 400
    # hand-written text outside entries is kept
    assert memory.memory_path(project).read_text().startswith("# Project memory")


def test_load_missing_and_truncated(project):
    assert memory.load(project) == ""
    for i in range(30):
        memory.append(project, f"note {i:02d} " + "y" * 50, today=DAY)
    text = memory.load(project, max_chars=300)
    assert text.startswith("[... older notes omitted")
    assert "note 29" in text and "note 00" not in text


def test_ensure_gitignored(git_project):
    gitignore = git_project / ".gitignore"
    gitignore.write_text("ignored/")  # no trailing newline
    assert memory.ensure_gitignored(git_project) is True
    assert gitignore.read_text() == "ignored/\n.academic/\n"
    assert memory.ensure_gitignored(git_project) is False
    gitignore.write_text("/.academic\n")
    assert memory.ensure_gitignored(git_project) is False


def test_ensure_gitignored_creates_file(git_project):
    (git_project / ".gitignore").unlink()
    assert memory.ensure_gitignored(git_project) is True
    assert (git_project / ".gitignore").read_text() == ".academic/\n"


def test_ensure_gitignored_not_a_repo(project):
    assert memory.ensure_gitignored(project) is False
    assert not (project / ".gitignore").exists()


# ---- protocol, policy and tool -------------------------------------------

def test_remember_schema():
    assert validate_action({"tool": "remember", "text": "x"}, 0).args == {"text": "x"}
    with pytest.raises(ProtocolError, match="missing 'text'"):
        validate_action({"tool": "remember"}, 0)


@pytest.mark.parametrize("mode", [DEFAULT, ACCEPT_EDITS, AUTO])
def test_remember_never_prompts(mode):
    assert not Approver(mode).needs_prompt("remember")


def test_remember_tool_saves_and_gitignores(git_project):
    from academic_agent.policy import Policy
    from academic_agent.session import Session
    from academic_agent.tools import Executor
    executor = Executor(Policy(git_project), Session(cwd=str(git_project), task="t"),
                        secrets=["s3cr3t-value"])
    prepared = executor.prepare(Action("remember", {"text": "Entry point: academic_agent/__main__.py"}))
    assert prepared.tier == "memory"
    result = prepared.execute()
    assert result.ok and result.status == "saved; added .academic/ to .gitignore"
    assert ".gitignore" in executor.session.touched
    assert ".academic/" in (git_project / ".gitignore").read_text()
    result = executor.prepare(Action("remember", {"text": "token s3cr3t-value"})).execute()
    assert not result.ok and "secret" in result.output
    result = executor.prepare(Action("remember", {"text": "Another fact"})).execute()
    assert result.status == "saved"


def test_remember_refuses_symlinked_memory_dir(executor, project, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / ".academic").symlink_to(outside)
    with pytest.raises(ToolError, match="outside the project root"):
        executor.prepare(Action("remember", {"text": "x"}))


# ---- context ---------------------------------------------------------------

def test_initial_prompt_includes_memory(project):
    assert "No project memory yet." in build_initial_prompt(project, "task")
    memory.append(project, "Data lives in data/raw", today=DAY)
    prompt = build_initial_prompt(project, "task")
    assert "Project memory (.academic/MEMORY.md" in prompt
    assert "AGENTS.md and the user take precedence" in prompt
    assert "- Data lives in data/raw  (2026-10-29)" in prompt
    assert prompt.index("AGENTS.md instructions:") < prompt.index("Project memory")
