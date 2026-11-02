"""Built-in skills: task-specific instructions added to the first prompt.

A skill is a Markdown file in this directory with a small header:

    ---
    name: review-pr
    description: one line
    trigger: regular expression matched against the task (case-insensitive)
    ---
    instructions ...
"""

import re
from dataclasses import dataclass
from pathlib import Path

SKILLS_DIR = Path(__file__).parent


@dataclass
class Skill:
    name: str
    description: str
    trigger: re.Pattern
    body: str


def parse_skill(text: str) -> Skill:
    """Parse a skill file; raises ValueError if the header is incomplete."""
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise ValueError("missing '---' header")
    header = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            header[key.strip()] = value.strip()
    missing = {"name", "description", "trigger"} - header.keys()
    if missing:
        raise ValueError("missing header fields: " + ", ".join(sorted(missing)))
    try:
        trigger = re.compile(header["trigger"], re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"invalid trigger: {exc}") from None
    return Skill(header["name"], header["description"], trigger,
                 text[match.end():].strip())


def load_skills(directory: Path = SKILLS_DIR) -> list[Skill]:
    skills = []
    for path in sorted(directory.glob("*.md")):
        try:
            skills.append(parse_skill(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise ValueError(f"skill {path.name}: {exc}") from None
    return skills


def matching_skills(task: str, skills: list[Skill] | None = None) -> list[Skill]:
    """Skills whose trigger occurs in the task."""
    skills = load_skills() if skills is None else skills
    return [s for s in skills if s.trigger.search(task)]
