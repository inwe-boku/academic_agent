import json
import subprocess

import pytest

from academic_agent import gitutil
from academic_agent import session as sessions
from academic_agent.__main__ import main
from academic_agent.api import ApiError, ChatResult, ModelInfo
from academic_agent.loop import Agent
from academic_agent.policy import AUTO, DEFAULT, Approver
from academic_agent.session import Session


class FakeApi:
    """Replays scripted replies (str, dict or exception)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, json_mode=True):
        self.calls.append([dict(m) for m in messages])
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            item = json.dumps(item)
        return ChatResult(item, prompt_tokens=100, completion_tokens=10)


@pytest.fixture
def inputs(monkeypatch):
    answers = []

    def fake_input(prompt=""):
        if not answers:
            raise EOFError
        return answers.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)
    return answers


def actions(*acts, reason=""):
    return {"type": "actions", "reason": reason, "actions": list(acts)}


DONE = {"type": "done", "message": "finished"}


def make_agent(root, replies, mode=DEFAULT, git_enabled=False, **kw):
    session = Session(cwd=str(root), task="task",
                      messages=[{"role": "user", "content": "first"}], **kw)
    api = FakeApi(replies)
    agent = Agent(root=root, api=api, session=session, approver=Approver(mode),
                  model_info=ModelInfo("m", 100_000, 0.000001, 0.00001),
                  git_enabled=git_enabled)
    return agent, api


def test_batch_runs_in_order_and_reports(project, inputs):
    (project / "a.txt").write_text("hello\n")
    agent, api = make_agent(project, [
        actions({"tool": "read_file", "path": "a.txt"},
                {"tool": "edit_file", "path": "a.txt", "old": "hello", "new": "bye"}),
        DONE,
    ])
    inputs += ["y", "y"]  # approve edit, accept done
    assert agent.run() == 0
    assert (project / "a.txt").read_text() == "bye\n"
    result_msg = api.calls[1][-1]["content"]
    assert result_msg.startswith("[1] read_file a.txt: OK\n    1  hello")
    assert "[2] edit_file a.txt: OK" in result_msg
    assert sessions.load(project) is None  # removed after accepting done
    assert agent.session.tokens_in == 200
    assert agent.session.cost_usd == pytest.approx(2 * (100e-6 + 10e-5))


def test_rejection_with_comment_stops_batch(project, inputs):
    agent, api = make_agent(project, [
        actions({"tool": "write_file", "path": "x.txt", "content": "x"},
                {"tool": "run", "command": "echo hi"}),
        DONE,
    ])
    inputs += ["call it y.txt", "y"]
    agent.run()
    assert not (project / "x.txt").exists()
    msg = api.calls[1][-1]["content"]
    assert "[1] write_file x.txt: REJECTED by user\nUser comment: call it y.txt" in msg
    assert "[2] run echo hi: SKIPPED" in msg


def test_failure_stops_batch_without_prompt(project, inputs):
    agent, api = make_agent(project, [
        actions({"tool": "read_file", "path": "../outside"},
                {"tool": "read_file", "path": "a.txt"}),
        DONE,
    ])
    inputs += ["y"]
    agent.run()
    msg = api.calls[1][-1]["content"]
    assert msg.startswith("[1] read_file ../outside: FAILED\n")
    assert "outside the project root" in msg
    assert "[2] read_file a.txt: SKIPPED" in msg


def test_auto_approve_still_asks_for_dangerous(project, inputs):
    (project / "d").mkdir()
    agent, api = make_agent(project, [
        actions({"tool": "run", "command": "echo safe"},
                {"tool": "run", "command": "rm -rf d"}),
        DONE,
    ], mode=AUTO)
    inputs += ["a", "n", "y"]  # 'a' is refused for dangerous, then reject
    agent.run()
    assert (project / "d").exists()
    msg = api.calls[1][-1]["content"]
    assert "[1] run echo safe: OK" in msg
    assert "[2] run rm -rf d: REJECTED by user" in msg


def test_always_for_tool(project, inputs):
    agent, _ = make_agent(project, [
        actions({"tool": "write_file", "path": "a.txt", "content": "a"}),
        actions({"tool": "write_file", "path": "b.txt", "content": "b"}),
        DONE,
    ])
    inputs += ["a", "y"]  # 'always' once, no prompt for the second write
    agent.run()
    assert (project / "b.txt").read_text() == "b"


def test_invalid_reply_is_corrected_without_user(project, inputs):
    agent, api = make_agent(project, ["not json", '{"type": "message", "message": "hi"}', DONE])
    inputs += ["y"]
    assert agent.run() == 0
    third = api.calls[2]
    assert third[-1]["content"].startswith("Invalid reply: unknown type 'message'")
    assert third[-2]["content"] == '{"type": "message", "message": "hi"}'
    # corrections are not kept in the history
    assert [m["content"] for m in agent.session.messages][:1] == ["first"]
    assert len(agent.session.messages) == 2


def test_three_invalid_replies_ask_the_user(project, inputs):
    agent, api = make_agent(project, ["bad", "bad", "bad", DONE])
    inputs += ["please use JSON", "y"]
    assert agent.run() == 0
    assert api.calls[3][-1]["content"] == "please use JSON"


def test_question_answer(project, inputs):
    agent, api = make_agent(project, [{"type": "question", "question": "Which?"}, DONE])
    inputs += ["the second", "y"]
    agent.run()
    assert api.calls[1][-1] == {"role": "user", "content": "the second"}


def test_done_not_accepted_continues(project, inputs):
    agent, api = make_agent(project, [DONE, DONE])
    inputs += ["n", "add tests", "y"]
    agent.run()
    assert api.calls[1][-1]["content"] == "add tests"


def test_step_limit(project, inputs):
    agent, api = make_agent(project, [actions({"tool": "list_dir"})] * 3 + [DONE])
    agent.max_steps = 2
    inputs += ["y", "y"]  # continue at the limit, accept done
    assert agent.run() == 0
    assert len(api.calls) == 4


def test_step_limit_stop_keeps_session(project, inputs):
    agent, _ = make_agent(project, [actions({"tool": "list_dir"})] * 2)
    agent.max_steps = 1
    inputs += ["n"]
    assert agent.run() == 0
    assert sessions.load(project) is not None


def test_resume_after_api_failure(project, inputs, monkeypatch):
    (project / "a.txt").write_text("x\n")
    agent, api = make_agent(project, [
        actions({"tool": "read_file", "path": "a.txt"}),
        ApiError("HTTP 401"),
    ])
    inputs += ["n"]  # do not retry now
    assert agent.run() == 1
    saved = sessions.load(project)
    assert saved.messages[-1]["content"].startswith("[1] read_file a.txt: OK")

    # resume through the CLI with a fresh fake API
    monkeypatch.chdir(project)
    for name, value in [("ACADEMIC_AI_BASE_URL", "https://h"), ("ACADEMIC_AI_CLIENT_ID", "i"),
                        ("ACADEMIC_AI_CLIENT_SECRET", "s"), ("ACADEMIC_AI_MODEL", "gpt-5")]:
        monkeypatch.setenv(name, value)
    fake = FakeApi([DONE])
    monkeypatch.setattr("academic_agent.__main__.ApiClient",
                        lambda *a, **k: type("C", (), {
                            "chat": fake.chat,
                            "model_info": lambda self: None})())
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    inputs += ["y"]
    assert main(["--resume"]) == 0
    assert fake.calls[0] == saved.messages
    assert sessions.load(project) is None


def test_api_error_retry_now(project, inputs):
    agent, api = make_agent(project, [ApiError("boom"), DONE])
    inputs += ["", "y"]  # Enter = retry (default yes), accept done
    assert agent.run() == 0


def test_compaction_with_summary(project, inputs):
    big = "x" * 20_000
    agent, api = make_agent(project, ["the summary", DONE])
    agent.budget.limit = 10_000
    agent.session.messages += sum(
        [[{"role": "assistant", "content": "a"}, {"role": "user", "content": big}]
         for _ in range(8)], [])
    inputs += ["y"]
    agent.run()
    assert api.calls[0][0]["content"].startswith("Summarise")
    assert agent.session.summaries == ["the summary"]
    assert "the summary" in api.calls[1][0]["content"]
    assert len(api.calls[1]) == 1 + 12


def test_compaction_fallback_stubs(project, inputs):
    result = "[1] read_file big.py: OK\n" + "line\n" * 5000
    agent, api = make_agent(project, [ApiError("summary failed"), DONE])
    agent.budget.limit = 10_000
    agent.session.messages += sum(
        [[{"role": "assistant", "content": "a"}, {"role": "user", "content": result}]
         for _ in range(8)], [])
    inputs += ["y"]
    agent.run()
    sent = api.calls[1]
    assert sent[2]["content"] == "[read_file big.py: 5000 lines, omitted]"
    assert sent[-1]["content"] == result


def test_redaction_in_results(project, inputs):
    (project / "a.txt").write_text("token: Bearer abcdefghijklmnopqrstuvwxyz\n")
    agent, api = make_agent(project, [actions({"tool": "read_file", "path": "a.txt"}), DONE])
    inputs += ["y"]
    agent.run()
    assert "abcdefghijklmnop" not in api.calls[1][-1]["content"]


def test_slash_commands_diff_and_undo(git_project, inputs, capsys):
    (git_project / "dirty.txt").write_text("untracked\n")
    agent, _ = make_agent(git_project, [
        actions({"tool": "read_file", "path": "a.txt"},
                {"tool": "edit_file", "path": "a.txt", "old": "two", "new": "TWO"},
                {"tool": "write_file", "path": "new.txt", "content": "new\n"}),
        DONE,
    ], mode=AUTO, git_enabled=True, start_commit=gitutil.head(git_project),
        dirty_at_start=sorted(gitutil.dirty_files(git_project)))
    inputs += ["/diff", "/undo", "y", "/cost", "y"]
    assert agent.run() == 0
    out = capsys.readouterr().out
    assert "+TWO" in out and "+new" in out
    assert "restore a.txt" in out and "delete  new.txt" in out
    assert "Tokens:" in out
    assert (git_project / "a.txt").read_text() == "one\ntwo\n"
    assert not (git_project / "new.txt").exists()
    assert (git_project / "dirty.txt").exists()
    # the index was not touched
    status = subprocess.run(["git", "status", "--porcelain"], cwd=git_project,
                            capture_output=True, text=True).stdout
    assert status.strip() == "?? dirty.txt"


def test_quit_keeps_session(project, inputs):
    agent, _ = make_agent(project, [{"type": "question", "question": "?"}])
    inputs += ["/quit"]
    assert agent.run() == 0
    assert sessions.load(project).messages[-1]["role"] == "assistant"


def test_non_tty_requires_auto_approve(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    for name in ("ACADEMIC_AI_BASE_URL", "ACADEMIC_AI_CLIENT_ID",
                 "ACADEMIC_AI_CLIENT_SECRET", "ACADEMIC_AI_MODEL"):
        monkeypatch.setenv(name, "x")
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["do", "it"]) == 2
    assert "--auto-approve" in capsys.readouterr().err
