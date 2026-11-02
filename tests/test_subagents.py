import json

import pytest

from academic_agent.api import ApiError, ChatResult
from academic_agent.context import build_initial_prompt
from academic_agent.policy import readonly_reason
from academic_agent.protocol import ProtocolError, parse_reply
from academic_agent.skills import load_skills, matching_skills, parse_skill
from academic_agent.subagents import Subagent, run_subagents


class FakeApi:
    """Replays scripted replies per sub-agent task (thread-safe enough)."""

    def __init__(self, replies):
        self.replies = {k: list(v) for k, v in replies.items()}
        self.calls = []

    def chat(self, messages, json_mode=True):
        self.calls.append([dict(m) for m in messages])
        task = messages[0]["content"].rsplit("Your task:\n", 1)[1]
        item = self.replies[task].pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            item = json.dumps(item)
        return ChatResult(item, prompt_tokens=100, completion_tokens=10)


def act(*actions):
    return {"type": "actions", "reason": "look", "actions": list(actions)}


def done(text):
    return {"type": "done", "message": text}


# ---- protocol --------------------------------------------------------------

def delegate(agents):
    return json.dumps(act({"tool": "delegate", "agents": agents}))


def test_delegate_parses():
    reply = parse_reply(delegate([{"name": "a", "task": "t"}]))
    assert reply.actions[0].tool == "delegate"


@pytest.mark.parametrize("agents", [
    [],
    [{"name": f"a{i}", "task": "t"} for i in range(7)],
    [{"name": "a"}],
    [{"name": "a", "task": " "}],
    [{"name": "a", "task": "t", "extra": 1}],
    [{"name": "a", "task": "t"}, {"name": "a", "task": "u"}],
    ["a"],
])
def test_delegate_invalid(agents):
    with pytest.raises(ProtocolError):
        parse_reply(delegate(agents))


# ---- read-only commands ----------------------------------------------------

@pytest.mark.parametrize("command", [
    "git show abc123:src/a.py",
    "git diff -w main...HEAD",
    "git log --oneline -n 5",
    "gh pr view 5 --json title,body",
    "gh pr diff 5",
    'gh api "repos/o/r/contents/a.py?ref=abc" -H "Accept: application/vnd.github.raw"',
    "gh api repos/o/r/pulls/5/comments --paginate",
])
def test_readonly_allowed(command, project):
    assert readonly_reason(command, project) is None


@pytest.mark.parametrize("command", [
    "git commit -m x",
    "git -c core.pager=sh log",
    "git diff --output=x.txt",
    "git grep -O vim foo",
    "git show HEAD | head",
    "git show $(whoami)",
    "git show `id`",
    "git log > out.txt",
    "git show HEAD; rm a",
    "gh pr comment 5 --body x",
    "gh pr view 5 --web",
    "gh api repos/o/r/issues -f title=x",
    "gh api repos/o/r/pulls/5/reviews --method POST --input r.json",
    "gh api -X DELETE repos/o/r",
    "cat a.py",
    "python -c 'print(1)'",
    "git show HEAD:/etc/passwd /etc/passwd",
])
def test_readonly_rejected(command, project):
    assert readonly_reason(command, project)


# ---- sub-agent loop --------------------------------------------------------

def make(project, replies, **kw):
    api = FakeApi({"t": replies})
    return Subagent("s", "t", api=api, root=project, log=lambda _: None, **kw), api


def test_subagent_reads_and_reports(project):
    (project / "a.py").write_text("x = 1\n")
    sub, api = make(project, [act({"tool": "read_file", "path": "a.py"}),
                              done("FINDING none")])
    result = sub.run()
    assert result.ok and result.report == "FINDING none"
    assert result.steps == 2 and result.prompt_tokens == 200
    assert "x = 1" in api.calls[1][-1]["content"]
    assert "Your task:\nt" in api.calls[0][0]["content"]


def test_subagent_cannot_write_or_run_arbitrary_commands(project):
    sub, api = make(project, [
        act({"tool": "write_file", "path": "b.py", "content": "x"},
            {"tool": "run", "command": "touch b.py"}),
        done("ok")])
    assert sub.run().ok
    feedback = api.calls[1][-1]["content"]
    assert "write_file is not available" in feedback
    assert "not allowed" in feedback
    assert not (project / "b.py").exists()


def test_subagent_question_is_answered_automatically(project):
    sub, api = make(project, [{"type": "question", "question": "?"}, done("r")])
    assert sub.run().report == "r"
    assert "cannot ask the user" in api.calls[1][-1]["content"]


def test_subagent_corrects_invalid_reply(project):
    sub, api = make(project, ["not json", done("r")])
    assert sub.run().report == "r"
    assert "Invalid reply" in api.calls[1][-1]["content"]


def test_subagent_step_limit_forces_report(project):
    read = act({"tool": "list_dir"})
    sub, api = make(project, [read, read, "plain text report"], max_steps=2)
    result = sub.run()
    assert result.ok and result.report == "plain text report"
    assert "Step limit reached" in api.calls[2][-1]["content"]


def test_subagent_api_error(project):
    sub, _ = make(project, [ApiError("boom")])
    result = sub.run()
    assert not result.ok and "boom" in result.report


def test_run_subagents_in_parallel_keeps_order(project):
    api = FakeApi({"t1": [done("one")], "t2": [RuntimeError("bad")]})
    results = run_subagents([{"name": "a", "task": "t1"}, {"name": "b", "task": "t2"}],
                            api=api, root=project, log=lambda _: None)
    assert [r.name for r in results] == ["a", "b"]
    assert results[0].report == "one" and results[0].ok
    assert not results[1].ok and "RuntimeError" in results[1].report


# ---- skills ----------------------------------------------------------------

def test_parse_skill():
    skill = parse_skill("---\nname: x\ndescription: d\ntrigger: \\bfoo\\b\n---\nbody\n")
    assert skill.name == "x" and skill.body == "body"
    assert skill.trigger.search("do FOO now")


@pytest.mark.parametrize("text", ["no header", "---\nname: x\n---\nbody",
                                  "---\nname: x\ndescription: d\ntrigger: (\n---\n"])
def test_parse_skill_invalid(text):
    with pytest.raises(ValueError):
        parse_skill(text)


def test_builtin_skills_load():
    assert "review-pr" in {s.name for s in load_skills()}


@pytest.mark.parametrize("task", ["review PR 119", "Please review pull request #5",
                                  "review the open PRs", "do a PR review of 7"])
def test_review_pr_triggers(task):
    assert [s.name for s in matching_skills(task)] == ["review-pr"]


@pytest.mark.parametrize("task", ["fix the tests", "write a review article",
                                  "create a PR for this change"])
def test_review_pr_does_not_trigger(task):
    assert matching_skills(task) == []


def test_skill_in_initial_prompt(project):
    assert "skill: review-pr" in build_initial_prompt(project, "review PR 3")
    assert "Skill instructions" not in build_initial_prompt(project, "fix bug")
