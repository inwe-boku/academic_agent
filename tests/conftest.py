import subprocess

import pytest

from academic_agent.policy import Policy
from academic_agent.session import Session
from academic_agent.tools import Executor


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Sessions go to a temporary XDG_STATE_HOME; no colour codes."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("NO_COLOR", "1")
    # set when these tests run inside an agent's `run` command
    monkeypatch.delenv("ACADEMIC_AGENT_NESTED", raising=False)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    return root.resolve()


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def git_project(project):
    git(project, "init", "-q")
    git(project, "config", "user.email", "test@example.com")
    git(project, "config", "user.name", "Test")
    (project / "a.txt").write_text("one\ntwo\n")
    (project / ".gitignore").write_text("ignored/\n")
    git(project, "add", ".")
    git(project, "commit", "-q", "-m", "init")
    return project


@pytest.fixture
def executor(project):
    session = Session(cwd=str(project), task="t")
    return Executor(Policy(project), session)
