#!/usr/bin/env python3

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import requests


# Base URL of the Academic AI platform (no trailing path), e.g. https://host.
# Endpoints are /api/v1/llm/chat and /api/v1/llm/models.
BASE_URL = os.environ.get(
    "ACADEMIC_AI_BASE_URL",
    "REPLACE_WITH_ACADEMIC_AI_BASE_URL",
).rstrip("/")

CLIENT_ID = os.environ.get("ACADEMIC_AI_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("ACADEMIC_AI_CLIENT_SECRET", "")
MODEL = os.environ.get("ACADEMIC_AI_MODEL", "REPLACE_WITH_MODEL_NAME")


SYSTEM_PROMPT = r"""
You are a terminal coding agent.

You work inside the user's current working directory.

Rules:
1. Read and obey AGENTS.md instructions supplied in the context.
2. Never assume that a file exists; inspect it first.
3. Prefer small, reversible changes.
4. Do not delete files, reset Git, overwrite unrelated files, or run destructive
   commands without explicitly asking for confirmation.
5. When work is needed, respond with valid JSON only, using one of these forms:

   {
     "type": "command",
     "command": "shell command",
     "reason": "why this command is needed"
   }

   {
     "type": "message",
     "message": "answer or explanation"
   }

   {
     "type": "done",
     "message": "summary of completed work"
   }

6. Use absolute paths only when necessary.
7. Do not use sudo unless the user explicitly approves it.
8. If a command might expose secrets, warn the user and ask for confirmation.
9. After receiving command output, decide what to do next.
"""


def find_agents_files(start: Path) -> list[Path]:
    """
    Finds AGENTS.md files from the filesystem root down to the current
    directory. More-specific files are appended later and therefore have
    higher priority in the context.
    """
    start = start.resolve()
    ancestors = list(start.parents)[::-1] + [start]

    result = []
    for directory in ancestors:
        candidate = directory / "AGENTS.md"
        if candidate.is_file():
            result.append(candidate)

    return result


def read_agents_files(cwd: Path) -> str:
    files = find_agents_files(cwd)

    if not files:
        return "No AGENTS.md file was found."

    sections = []
    for file in files:
        try:
            content = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = file.read_text(errors="replace")

        sections.append(f"--- {file} ---\n{content}")

    return "\n\n".join(sections)


def collect_context(cwd: Path) -> str:
    """
    Collect a conservative, text-only directory context.
    Avoids sending hidden directories, .git, virtual environments, and common
    secret files automatically.
    """
    ignored_directories = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".cache",
        "dist",
        "build",
    }

    ignored_names = {
        ".env",
        ".env.local",
        ".env.production",
        "id_rsa",
        "id_ed25519",
    }

    lines = []

    for root, directories, files in os.walk(cwd):
        directories[:] = sorted(
            d for d in directories
            if d not in ignored_directories and not d.startswith(".")
        )

        relative_root = Path(root).relative_to(cwd)

        for filename in sorted(files):
            if filename in ignored_names:
                continue

            path = Path(root) / filename
            relative_path = path.relative_to(cwd)

            lines.append(str(relative_path))

    return "\n".join(lines[:2000])


def build_initial_prompt(cwd: Path, task: str) -> str:
    agents = read_agents_files(cwd)
    tree = collect_context(cwd)

    return f"""
Current working directory:
{cwd}

User task:
{task}

Repository file listing:
{tree}

AGENTS.md instructions:
{agents}

Determine the next safe action.
"""


def api_headers() -> dict:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError(
            "ACADEMIC_AI_CLIENT_ID / ACADEMIC_AI_CLIENT_SECRET are not set."
        )

    if BASE_URL.startswith("REPLACE_WITH"):
        raise RuntimeError(
            "ACADEMIC_AI_BASE_URL is still a placeholder. Set it to the "
            "host of the Academic AI platform."
        )

    return {
        "X-Client-ID": CLIENT_ID,
        "X-Client-Secret": CLIENT_SECRET,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def call_academic_ai(messages: list[dict]) -> str:
    """
    POST {BASE_URL}/api/v1/llm/chat (stateless, no streaming).
    The full message history is sent on every call.
    """
    response = requests.post(
        f"{BASE_URL}/api/v1/llm/chat",
        headers=api_headers(),
        json={"model": MODEL, "messages": messages},
        timeout=180,
    )

    if not response.ok:
        raise RuntimeError(
            f"Academic AI API returned HTTP {response.status_code}:\n"
            f"{response.text[:4000]}"
        )

    data = response.json()

    try:
        return data["data"]["content"]
    except (KeyError, TypeError):
        raise RuntimeError(
            "Could not find assistant text in the API response.\n"
            + json.dumps(data, indent=2)[:4000]
        )


def list_models() -> list[dict]:
    response = requests.get(
        f"{BASE_URL}/api/v1/llm/models",
        headers=api_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["data"]


def display_command(command: str, reason: str) -> None:
    print("\nProposed command:")
    print(f"  {command}")
    print(f"\nReason: {reason}")


def command_is_potentially_dangerous(command: str) -> bool:
    dangerous_fragments = [
        "rm -rf",
        "rm -r",
        "git reset --hard",
        "git clean",
        "mkfs",
        "dd if=",
        "shutdown",
        "reboot",
        "poweroff",
        "sudo ",
        "> /dev/",
    ]

    lowered = command.lower()
    return any(fragment in lowered for fragment in dangerous_fragments)


def execute_command(command: str, cwd: Path) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        shell=True,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=300,
    )

    output = completed.stdout or ""
    return completed.returncode, output[-12000:]


def parse_model_response(text: str) -> dict:
    """
    Handles plain JSON and JSON enclosed in a Markdown code block.
    """
    cleaned = text.strip()

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        cleaned = "\n".join(lines).strip()

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "type": "message",
            "message": text,
        }

    if not isinstance(result, dict):
        return {
            "type": "message",
            "message": text,
        }

    return result


def ask_confirmation(command: str) -> bool:
    answer = input("\nExecute this command? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Academic AI terminal coding agent"
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="Print the available models and exit",
    )
    parser.add_argument(
        "task",
        nargs="*",
        help="Task to perform in the current directory",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Execute commands without asking individually",
    )
    args = parser.parse_args()

    if args.list_models:
        try:
            for model in list_models():
                print(
                    f"{model['modelName']}  context={model['contextWindow']}  "
                    f"max_output={model['outputTokenLimit']}"
                )
        except Exception as exc:
            print(f"API error: {exc}", file=sys.stderr)
            return 1
        return 0

    if not args.task:
        parser.error("a task is required")

    cwd = Path.cwd().resolve()
    task = " ".join(args.task)

    # The API only accepts the roles "user" and "assistant", so the system
    # prompt is prepended to the first user message.
    messages = [
        {
            "role": "user",
            "content": SYSTEM_PROMPT.strip()
            + "\n\n"
            + build_initial_prompt(cwd, task),
        },
    ]

    for step in range(30):
        print(f"\n--- Agent step {step + 1} ---")

        try:
            answer = call_academic_ai(messages)
        except Exception as exc:
            print(f"API error: {exc}", file=sys.stderr)
            return 1

        action = parse_model_response(answer)
        action_type = action.get("type")

        if action_type == "message":
            print(action.get("message", answer))
            messages.append({"role": "assistant", "content": answer})

            follow_up = input("\nContinue? [y/N] ").strip().lower()
            if follow_up not in {"y", "yes"}:
                return 0

            messages.append(
                {
                    "role": "user",
                    "content": "Continue with the task. Inspect the files if necessary.",
                }
            )
            continue

        if action_type == "done":
            print(action.get("message", "Task completed."))
            return 0

        if action_type != "command":
            print("Unrecognized model response:")
            print(answer)
            return 1

        command = action.get("command")
        reason = action.get("reason", "")

        if not isinstance(command, str) or not command.strip():
            print("The model returned an invalid command.")
            return 1

        display_command(command, reason)

        if command_is_potentially_dangerous(command):
            print("\nWarning: this command appears potentially destructive.")

        if not args.auto_approve and not ask_confirmation(command):
            messages.append({"role": "assistant", "content": answer})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "The user rejected the proposed command. "
                        "Propose a safer alternative or explain what is needed."
                    ),
                }
            )
            continue

        try:
            return_code, output = execute_command(command, cwd)
        except subprocess.TimeoutExpired:
            return_code = 124
            output = "Command timed out after 300 seconds."

        print("\nCommand output:")
        print(output if output else "(no output)")
        print(f"\nExit code: {return_code}")

        messages.append({"role": "assistant", "content": answer})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"The command was:\n{command}\n\n"
                    f"Exit code: {return_code}\n\n"
                    f"Output:\n{output}"
                ),
            }
        )

    print("Stopped after reaching the maximum number of agent steps.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
