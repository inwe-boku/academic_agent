import json
import stat

from academic_agent import session as sessions
from academic_agent.session import Session, redact


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_save_permissions_and_roundtrip(project):
    s = Session(cwd=str(project), task="t", messages=[{"role": "user", "content": "x"}],
                touched={"a.py": {"created": True}}, start_commit="abc")
    sessions.save(s)
    path = sessions.session_path(project)
    assert mode(path) == 0o600
    assert mode(path.parent) == 0o700
    assert not path.with_suffix(".tmp").exists()
    loaded = sessions.load(project)
    assert loaded == s


def test_existing_directory_is_tightened(project):
    directory = sessions.state_dir()
    directory.mkdir(parents=True, mode=0o755)
    directory.chmod(0o755)
    sessions.save(Session(cwd=str(project), task="t"))
    assert mode(directory) == 0o700


def test_old_session_format_loads(project):
    path = sessions.session_path(project)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"cwd": str(project), "task": "t",
                                "messages": [{"role": "user", "content": "x"}]}))
    loaded = sessions.load(project)
    assert loaded.task == "t" and loaded.touched == {}


def test_list_and_clear(project):
    sessions.save(Session(cwd=str(project), task="my task"))
    rows = sessions.list_sessions()
    assert [r["task"] for r in rows] == ["my task"]
    assert sessions.clear(project)
    assert sessions.load(project) is None
    assert not sessions.clear(project)


def test_redact_patterns():
    text = (
        "Authorization: Bearer abcdefghijklmnop\n"
        "key=sk-ABCDEFGHIJKLMNOPQRSTUV\n"
        "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----\n"
        "client secret: hunter2hunter2\n"
    )
    out = redact(text, ["hunter2hunter2"])
    assert "abcdefghijklmnop" not in out and "Bearer [REDACTED]" in out
    assert "sk-ABC" not in out
    assert "MIIabc" not in out and "[REDACTED PRIVATE KEY]" in out
    assert "hunter2" not in out
    assert redact("nothing secret") == "nothing secret"
