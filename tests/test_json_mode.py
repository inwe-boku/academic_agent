"""--json: non-interactive runs for programs such as Claude Code."""

import json

import pytest

from academic_agent import session as sessions
from academic_agent.__main__ import main
from academic_agent.api import ApiError

from .test_loop import DONE, FakeApi, actions


class FakeClient(FakeApi):
    def model_info(self):
        return None


@pytest.fixture
def cli(project, monkeypatch, capsys):
    """Run main() in project with scripted replies; returns (code, result, err)."""
    monkeypatch.chdir(project)
    for name in ("ACADEMIC_AI_BASE_URL", "ACADEMIC_AI_CLIENT_ID",
                 "ACADEMIC_AI_CLIENT_SECRET", "ACADEMIC_AI_MODEL"):
        monkeypatch.setenv(name, "x")

    def no_input(prompt=""):
        raise AssertionError(f"--json run read stdin: {prompt!r}")

    monkeypatch.setattr("builtins.input", no_input)
    api = FakeClient([])
    monkeypatch.setattr("academic_agent.__main__.ApiClient", lambda *a, **k: api)

    def run(*argv, replies=()):
        api.replies.extend(replies)
        code = main(list(argv))
        out, err = capsys.readouterr()
        lines = out.splitlines()
        assert len(lines) == 1, f"stdout must hold one JSON line, got: {out!r}"
        return code, json.loads(lines[0]), err

    run.api = api
    return run


def test_done(cli, project):
    code, result, err = cli("--auto-approve", "--json", "make a file", replies=[
        actions({"tool": "write_file", "path": "new.txt", "content": "hi\n"}),
        {"type": "done", "message": "created new.txt"},
    ])
    assert code == 0
    assert result["version"] == 1 and result["status"] == "done"
    assert result["message"] == "created new.txt"
    assert result["changed_files"] == ["new.txt"]
    assert result["steps"] == 2 and result["session_kept"] is False
    assert len(result["timings"]) == 2 and result["timings"][0]["calls"] == 1
    assert "Agent completion" in err  # human output went to stderr
    assert sessions.load(project) is None


def test_question_then_resume_with_answer(cli, project):
    code, result, _ = cli("--auto-approve", "--json", "task", replies=[
        {"type": "question", "question": "Which file?"}])
    assert (code, result["status"], result["message"]) == (3, "question", "Which file?")
    assert result["session_kept"] is True
    code, result, _ = cli("--auto-approve", "--json", "--resume", "a.txt",
                          replies=[DONE])
    assert (code, result["status"]) == (0, "done")
    assert cli.api.calls[-1][-1] == {"role": "user", "content": "a.txt"}


def test_dangerous_command_blocked_then_approved_once(cli, project):
    (project / "build").mkdir()
    rm = {"tool": "run", "command": "rm -rf build"}
    code, result, _ = cli("--auto-approve", "--json", "clean", replies=[
        actions({"tool": "list_dir"}, rm, {"tool": "run", "command": "echo after"})])
    assert (code, result["status"]) == (4, "blocked")
    assert result["blocked_command"] == "rm -rf build"
    assert "rm" in result["reason"]
    assert (project / "build").exists()
    saved = sessions.load(project)
    assert saved.blocked_command == "rm -rf build"
    report = saved.messages[-1]["content"]
    assert "[1] list_dir .: OK" in report
    assert "[2] run rm -rf build: BLOCKED" in report
    assert "[3] run echo after: SKIPPED" in report

    # approved: exactly this command runs once; another dangerous one is blocked
    code, result, _ = cli("--auto-approve", "--json", "--resume", "--approve-blocked",
                          replies=[actions(rm), actions({"tool": "run", "command": "rm -rf src"})])
    assert "Run it again exactly as before:\nrm -rf build" in cli.api.calls[-2][-1]["content"]
    assert not (project / "build").exists()
    assert (code, result["status"], result["blocked_command"]) == (4, "blocked", "rm -rf src")
    assert sessions.load(project).approved_command is None


def test_approved_command_must_match_exactly(cli, project):
    (project / "build").mkdir()
    cli("--auto-approve", "--json", "clean",
        replies=[actions({"tool": "run", "command": "rm -rf build"})])
    code, result, _ = cli("--auto-approve", "--json", "--resume", "--approve-blocked",
                          replies=[actions({"tool": "run", "command": "rm -rf build ~"})])
    assert (code, result["status"]) == (4, "blocked")
    assert (project / "build").exists()


def test_approve_blocked_without_blocked_command(cli, project):
    cli("--auto-approve", "--json", "t", replies=[{"type": "question", "question": "?"}])
    code, result, _ = cli("--auto-approve", "--json", "--resume", "--approve-blocked")
    assert (code, result["status"]) == (1, "error")
    assert "no blocked command" in result["message"]


def test_step_limit(cli):
    code, result, _ = cli("--auto-approve", "--json", "--max-steps", "1", "t",
                          replies=[actions({"tool": "list_dir"})])
    assert (code, result["status"]) == (5, "step_limit")


def test_api_error_keeps_session(cli, project):
    code, result, _ = cli("--auto-approve", "--json", "t",
                          replies=[ApiError("HTTP 401", 401)])
    assert (code, result["status"]) == (1, "error")
    assert "HTTP 401" in result["message"]
    assert sessions.load(project) is not None


def test_invalid_replies(cli):
    code, result, _ = cli("--auto-approve", "--json", "t", replies=["no json"] * 3)
    assert (code, result["status"]) == (1, "error")
    assert "invalid replies" in result["message"]


def test_json_needs_auto_approve(cli):
    code, result, _ = cli("--json", "t")
    assert (code, result["status"]) == (2, "error")
    assert "--auto-approve" in result["message"]


def test_usage_error_still_prints_json(cli):
    code, result, _ = cli("--auto-approve", "--json")
    assert (code, result["status"]) == (2, "error")


def test_nested_start_refused(cli, monkeypatch):
    monkeypatch.setenv("ACADEMIC_AGENT_NESTED", "1")
    code, result, _ = cli("--auto-approve", "--json", "t")
    assert (code, result["status"]) == (2, "error")
    assert "cannot be started" in result["message"]


def test_commands_get_nested_marker(executor):
    from academic_agent.protocol import Action
    out = executor.prepare(Action("run", {"command": "echo $ACADEMIC_AGENT_NESTED"})).execute()
    assert out.output.splitlines()[-1] == "1"
