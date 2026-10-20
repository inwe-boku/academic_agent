#!/usr/bin/env python3

import argparse
import json
import os
import shlex
import hashlib
import subprocess
import sys
import time
from pathlib import Path

import requests

# Extra stdlib imports for a friendlier TUI (no new deps)
import threading
import itertools
import shutil
import textwrap


# Base URL of the Academic AI platform (no trailing path), e.g. https://host.
# Endpoints are /api/v1/llm/chat and /api/v1/llm/models.
BASE_URL = os.environ.get(
    "ACADEMIC_AI_BASE_URL",
    "REPLACE_WITH_ACADEMIC_AI_BASE_URL",
).rstrip("/")

CLIENT_ID = os.environ.get("ACADEMIC_AI_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("ACADEMIC_AI_CLIENT_SECRET", "")
MODEL = os.environ.get("ACADEMIC_AI_MODEL", "REPLACE_WITH_MODEL_NAME")

# Seconds to wait between retries of a failed API call (one entry per retry).
RETRY_DELAYS = [2, 5, 15, 30]

# Sessions are stored outside the project, one file per working directory.
STATE_DIR = (
    Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    / "academic-agent"
)


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
     "type": "question",
     "question": "a question for the user that you need answered to proceed"
   }

   {
     "type": "done",
     "message": "summary of completed work"
   }

6. Use absolute paths only when necessary.
7. Do not use sudo unless the user explicitly approves it.
8. If a command might expose secrets, warn the user and ask for confirmation.
9. After receiving command output, decide what to do next.
10. If requirements are ambiguous or you need a decision or information from the
    user, use the "question" type instead of guessing. The user's free-text
    answer is returned in the next message. Ask one focused question at a time.
11. The user may reject a command and add a comment; follow that comment.
"""



# ---- Simple TUI helpers (colors, sections, spinner) ----
def _is_tty():
    try:
        return sys.stdout.isatty()
    except Exception:
        return False

NO_COLOR = os.environ.get('NO_COLOR') is not None
USE_COLOR = _is_tty() and not NO_COLOR

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
FG_RED = "\033[31m"
FG_GREEN = "\033[32m"
FG_YELLOW = "\033[33m"
FG_BLUE = "\033[34m"
FG_MAGENTA = "\033[35m"
FG_CYAN = "\033[36m"

def color(text: str, *codes: str) -> str:
    if not USE_COLOR:
        return text
    return ''.join(codes) + text + RESET

def hr(char='-', width=None):
    if width is None:
        try:
            width = shutil.get_terminal_size((80, 20)).columns
        except Exception:
            width = 80
    return char * max(20, min(120, width))

class Spinner:
    FRAMES = ('⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏')

    def __init__(self, message: str = '', interval: float = 0.1, enabled: bool = None):
        self.message = message
        self.interval = interval
        self.enabled = _is_tty() if enabled is None else enabled
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if not self.enabled:
            if self.message:
                print(self.message)
            return self
        def run():
            frames = itertools.cycle(self.FRAMES)
            prefix = color(self.message, FG_CYAN, BOLD) + ' ' if self.message else ''
            while not self._stop.is_set():
                frame = next(frames)
                sys.stdout.write(f"\r{prefix}{color(frame, FG_CYAN)} ")
                sys.stdout.flush()
                time.sleep(self.interval)
            try:
                width = shutil.get_terminal_size((80, 20)).columns
            except Exception:
                width = 80
            sys.stdout.write('\r' + ' ' * width + '\r')
            sys.stdout.flush()
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if not self.enabled:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        self.stop()

def print_banner(cwd: Path, task: str, model: str):
    title = f"Academic Agent — {cwd}"
    print(hr('━'))
    print(color(title, BOLD, FG_BLUE))
    print(color(f"Model: {model}", DIM))
    print(color("Task:", BOLD), task)
    print(hr('━'))

def print_section(title: str, icon: str = '•', color_code: str = FG_CYAN):
    print()
    print(color(f"{icon} {title}", BOLD, color_code))

def print_summary(run_log: list[dict]):
    if not run_log:
        print(color('No commands were executed in this session.', DIM))
        return
    ok = sum(1 for r in run_log if r.get('return_code', 1) == 0)
    fail = sum(1 for r in run_log if r.get('return_code', 1) != 0)
    print(color('Summary:', BOLD, FG_MAGENTA))
    print(f'Steps: {len(run_log)}  Success: {ok}  Failed: {fail}')
    for i, r in enumerate(run_log, 1):
        rc = r.get('return_code', 0)
        status = 'OK' if rc == 0 else f'ERR {rc}'
        cmd = r.get('command', '')
        if len(cmd) > 90:
            cmd = cmd[:87] + '…'
        print(f'  {i:2d}. {status}  {cmd}')

def confirm_exit(run_log: list[dict], note: str | None = None) -> bool:
    if note:
        print(color(note, FG_YELLOW))
    print_summary(run_log)
    ans = input("\nExit the agent now? [y/N] ").strip().lower()
    return ans in {"y", "yes"}

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


class TransientAPIError(RuntimeError):
    """Network problem or HTTP 429/5xx; worth retrying."""


def call_academic_ai(messages: list[dict]) -> str:
    """
    Calls the API, retrying transient failures with increasing delays.
    """
    with Spinner('🤖 Thinking with Academic AI...', interval=0.12):
        for attempt in range(len(RETRY_DELAYS) + 1):
            try:
                return _call_academic_ai_once(messages)
            except TransientAPIError as exc:
                if attempt == len(RETRY_DELAYS):
                    raise
                delay = RETRY_DELAYS[attempt]
                print(
                    f"Transient API error ({exc}); retrying in {delay}s "
                    f"({attempt + 1}/{len(RETRY_DELAYS)})...",
                    file=sys.stderr,
                )
                time.sleep(delay)

def _call_academic_ai_once(messages: list[dict]) -> str:
    """
    POST {BASE_URL}/api/v1/llm/chat (stateless, no streaming).
    The full message history is sent on every call.
    """
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/llm/chat",
            headers=api_headers(),
            json={"model": MODEL, "messages": messages},
            timeout=180,
        )
    except (requests.ConnectionError, requests.Timeout) as exc:
        raise TransientAPIError(type(exc).__name__) from exc

    if response.status_code == 429 or response.status_code >= 500:
        raise TransientAPIError(f"HTTP {response.status_code}")

    if not response.ok:
        raise RuntimeError(
            f"Academic AI API returned HTTP {response.status_code}:\n"
            f"{response.text[:4000]}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise TransientAPIError("invalid JSON in response") from exc

    try:
        return data["data"]["content"]
    except (KeyError, TypeError):
        raise RuntimeError(
            "Could not find assistant text in the API response.\n"
            + json.dumps(data, indent=2)[:4000]
        )


def session_path(cwd: Path) -> Path:
    digest = hashlib.sha256(str(cwd).encode()).hexdigest()[:16]
    return STATE_DIR / f"{digest}.json"


def save_session(cwd: Path, task: str, messages: list[dict]) -> None:
    """Persist the history so a failed run can be continued with --resume."""
    try:
        path = session_path(cwd)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"cwd": str(cwd), "task": task, "messages": messages}),
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError as exc:
        print(f"Warning: could not save session: {exc}", file=sys.stderr)


def load_session(cwd: Path) -> dict | None:
    try:
        return json.loads(session_path(cwd).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def clear_session(cwd: Path) -> None:
    session_path(cwd).unlink(missing_ok=True)


def list_models() -> list[dict]:
    response = requests.get(
        f"{BASE_URL}/api/v1/llm/models",
        headers=api_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["data"]


def display_command(command: str, reason: str) -> None:
    # Print the reasoning for this step and then the actual shell command
    if reason:
        try:
            width = shutil.get_terminal_size((80, 20)).columns
        except Exception:
            width = 80
        for paragraph in str(reason).splitlines():
            if not paragraph.strip():
                print()
                continue
            for line in textwrap.wrap(paragraph, width=max(20, min(120, width)) - 4):
                print('  ' + color(line, BOLD))
    # Always show the command (bold), but do not show any prompts
    if command:
        print(color(command, BOLD))
def display_question(question: str) -> None:
    print_section('Question', icon='❓', color_code=FG_MAGENTA)
    try:
        width = shutil.get_terminal_size((80, 20)).columns
    except Exception:
        width = 80
    import textwrap
    for paragraph in str(question).splitlines():
        if not paragraph.strip():
            print()
            continue
        for line in textwrap.wrap(paragraph, width=max(20, min(120, width)) - 4):
            print('  ' + color(line, BOLD))


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
    with Spinner('⏳ Running shell command...', interval=0.1):
        completed = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=300,
        )
    output = completed.stdout or ''
    return completed.returncode, output[-12000:]

def run_post_checks_and_cleanup(cwd: Path) -> None:
    """Run mandatory post-run checks and remove common backup files.

    Checks:
    - Python syntax check for all files: python -m compileall .
    - mkdocs build --strict (only if mkdocs.yml exists and mkdocs is installed)

    Cleanup:
    - Remove files matching: *.bak, *~, *.swp, *.swx, *.tmp, *.orig, *.rej
    """
    print_section('Post-run checks and cleanup', icon='🧹', color_code=FG_GREEN)

    # 1) Python syntax check
    try:
        py_check = subprocess.run(
            [sys.executable, '-m', 'compileall', '-q', '-x', r'(^|/)(\.venv|venv|node_modules|site|build|dist|__pycache__)(/|$)', '.'],
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        status = 'OK' if py_check.returncode == 0 else 'FAILED'
        print(f"- Python syntax check: {status}")
        if py_check.returncode != 0 and py_check.stdout:
            print(py_check.stdout[-2000:])
    except Exception as exc:
        print(f"- Python syntax check: FAILED ({exc})")

    # 2) MkDocs strict build (if configured and available)
    mkdocs_cfg = cwd / 'mkdocs.yml'
    if mkdocs_cfg.is_file():
        try:
            mk = subprocess.run(
                [sys.executable, '-m', 'mkdocs', 'build', '--strict'],
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            status = 'OK' if mk.returncode == 0 else 'FAILED'
            print(f"- MkDocs build: {status}")
            if mk.returncode != 0 and mk.stdout:
                print(mk.stdout[-2000:])
        except Exception as exc:
            print(f"- MkDocs build: FAILED ({exc})")
    else:
        print('- MkDocs build: SKIPPED')

    # 3) Cleanup common backup files
    patterns = ['*.bak', '*~', '*.swp', '*.swx', '*.tmp', '*.orig', '*.rej']
    removed = 0
    for pattern in patterns:
        for path in cwd.rglob(pattern):
            if path.is_file():
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
    print(f"- Removed backup files: {removed}")


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


def ask_confirmation(command: str) -> tuple[bool, str]:
    """Return (approved, feedback). Any text other than y/n is feedback.
    Shows a clear prompt that input is required.
    """
    prompt = color('\nExecute this command? ', BOLD, FG_GREEN) + '[y/N, or type a comment to reject with feedback] '
    answer = input(prompt).strip()
    if answer.lower() in {'y', 'yes'}:
        return True, ''
    if answer.lower() in {'', 'n', 'no'}:
        return False, ''
    return False, answer

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
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue the last session of this directory (e.g. after an "
        "API failure) instead of starting a new one",
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

    cwd = Path.cwd().resolve()

    if args.resume:
        session = load_session(cwd)
        if not session:
            print("No saved session found for this directory.", file=sys.stderr)
            return 1
        task = session["task"]
        messages = session["messages"]
        if args.task:
            messages.append({"role": "user", "content": " ".join(args.task)})
        elif messages[-1]["role"] == "assistant":
            messages.append(
                {"role": "user", "content": "Continue with the task."}
            )
        print(f"Resuming session: {task}")
    else:
        if not args.task:
            parser.error("a task is required (or use --resume)")

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

    run_log: list[dict] = []
    try:
        print_banner(cwd, task, MODEL)
    except Exception:
        pass

    step = 0
    while True:
            step += 1
            # print(f"\n--- Agent step {step} ---")

            # History ends with a user message here, so it can be resumed as is.
            save_session(cwd, task, messages)

            try:
                answer = call_academic_ai(messages)
            except Exception as exc:
                print(f"API error: {exc}", file=sys.stderr)
                print(
                    "Progress is saved. Continue with: academic --resume",
                    file=sys.stderr,
                )
                if confirm_exit(run_log, note='An API error occurred.'):
                    run_post_checks_and_cleanup(cwd)
                    return 1
                else:
                    time.sleep(2)
                    continue

            action = parse_model_response(answer)
            action_type = action.get("type")

            if action_type == "message":
                print(action.get("message", answer))
                messages.append({"role": "assistant", "content": answer})

                reply = input(
                    "\nReply (y = continue, Enter/n = stop, or type your answer): "
                ).strip()
                if reply.lower() in {"", "n", "no"}:
                    if confirm_exit(run_log, note='Stopping after a message from the agent.'):
                        run_post_checks_and_cleanup(cwd)
                        clear_session(cwd)
                        return 0
                    else:
                        reply = input('Type your next instruction to continue: ').strip()
                        if not reply:
                            reply = 'Continue with the task. Inspect the files if necessary.'
                        messages.append({'role': 'user', 'content': reply})
                        continue

                if reply.lower() in {"y", "yes"}:
                    reply = "Continue with the task. Inspect the files if necessary."
                messages.append({"role": "user", "content": reply})
                continue

            if action_type == "question":
                question = action.get("question") or action.get("message") or answer
                display_question(question)
                messages.append({"role": "assistant", "content": answer})

                reply = input(color('Your answer (empty to stop): ', BOLD, FG_GREEN)).strip()
                if not reply:
                    if confirm_exit(run_log, note='The agent asked a question.'):
                        run_post_checks_and_cleanup(cwd)
                        clear_session(cwd)
                        return 0
                    else:
                        reply = input('Provide an answer to continue: ').strip()
                        if not reply:
                            reply = 'Please proceed with reasonable defaults and explain choices.'

                messages.append({"role": "user", "content": reply})
                continue

            if action_type == "done":
                print_section('Agent completion', icon='✅', color_code=FG_GREEN)
                print(action.get('message', 'Task completed.'))
                print_summary(run_log)
                if confirm_exit(run_log, note='The agent signaled completion.'):
                    run_post_checks_and_cleanup(cwd)
                    clear_session(cwd)
                    return 0
                else:
                    follow = input('Enter next instruction to continue (or press Enter to let the agent decide): ').strip()
                    if not follow:
                        follow = 'Continue with follow-up improvements if any. Summarize changes before proposing new commands.'
                    messages.append({'role': 'assistant', 'content': answer})
                    messages.append({'role': 'user', 'content': follow})
                    continue



            if action_type != "command":
                print("Unrecognized model response:")

                print(answer)

                run_post_checks_and_cleanup(cwd)

                return 1

            command = action.get("command")
            reason = action.get("reason", "")

            if not isinstance(command, str) or not command.strip():
                print("The model returned an invalid command.")

                run_post_checks_and_cleanup(cwd)

                return 1

            display_command(command, reason)

            if command_is_potentially_dangerous(command):
                print("\nWarning: this command appears potentially destructive.")

            if args.auto_approve:
                approved, feedback = True, ""
            else:
                approved, feedback = ask_confirmation(command)

            if not approved:
                content = (
                    "The user rejected the proposed command. "
                    "Propose a safer alternative or explain what is needed."
                )
                if feedback:
                    content += f"\n\nUser comment: {feedback}"
                messages.append({"role": "assistant", "content": answer})
                messages.append({"role": "user", "content": content})
                continue

            try:
                return_code, output = execute_command(command, cwd)
            except subprocess.TimeoutExpired:
                return_code = 124
                output = "Command timed out after 300 seconds."


            run_log.append({'command': command, 'return_code': return_code})

            messages.append({'role': 'assistant', 'content': answer})
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
        


if __name__ == "__main__":
    raise SystemExit(main())
