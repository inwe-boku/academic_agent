import pytest

from academic_agent.protocol import ProtocolError, parse_reply

ACTIONS = '{"type": "actions", "reason": "look", "actions": [{"tool": "read_file", "path": "a.py"}]}'


def test_plain_json():
    reply = parse_reply(ACTIONS)
    assert reply.type == "actions" and reply.reason == "look"
    assert reply.actions[0].tool == "read_file"
    assert reply.actions[0].args == {"path": "a.py"}


def test_fenced_json():
    assert parse_reply(f"```json\n{ACTIONS}\n```").type == "actions"
    assert parse_reply(f"```\n{ACTIONS}\n```").type == "actions"


def test_prose_around_json():
    text = f"Sure, here is my plan:\n{ACTIONS}\nLet me know."
    assert parse_reply(text).actions[0].args["path"] == "a.py"


def test_prefers_object_with_type():
    text = 'Example {"a": 1} then {"type": "done", "message": "ok"}'
    reply = parse_reply(text)
    assert reply.type == "done" and reply.text == "ok"


def test_question_and_done():
    assert parse_reply('{"type": "question", "question": "Which?"}').text == "Which?"
    assert parse_reply('{"type": "done", "message": "All good"}').text == "All good"


def test_several_actions():
    reply = parse_reply('{"type": "actions", "actions": ['
                        '{"tool": "run", "command": "pytest", "timeout": 30},'
                        '{"tool": "move_file", "from": "a", "to": "b"},'
                        '{"tool": "list_dir"}]}')
    assert [a.tool for a in reply.actions] == ["run", "move_file", "list_dir"]


@pytest.mark.parametrize("text, error", [
    ("no json here", "no JSON object"),
    ("[1, 2]", "no JSON object"),
    ('{"type": "message", "message": "hi"}', "unknown type 'message'"),
    ('{"type": "command", "command": "ls"}', "unknown type"),
    ('{"type": "actions", "actions": []}', "non-empty list"),
    ('{"type": "actions", "actions": [{"tool": "rm"}]}', "unknown tool"),
    ('{"type": "actions", "actions": [{"tool": "read_file"}]}', "missing 'path'"),
    ('{"type": "actions", "actions": [{"tool": "read_file", "path": 1}]}', "type str"),
    ('{"type": "actions", "actions": [{"tool": "read_file", "path": "a", "limit": true}]}',
     "type int"),
    ('{"type": "actions", "actions": [{"tool": "read_file", "path": "a", "x": 1}]}',
     "unknown argument 'x'"),
    ('{"type": "question", "question": ""}', "non-empty"),
])
def test_invalid(text, error):
    with pytest.raises(ProtocolError, match=error):
        parse_reply(text)
