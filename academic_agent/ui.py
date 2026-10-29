"""Terminal output: colours, spinner, prompts, diffs and summaries."""

import itertools
import os
import shutil
import sys
import textwrap
import threading
import time

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
FG_RED = "\033[31m"
FG_GREEN = "\033[32m"
FG_YELLOW = "\033[33m"
FG_BLUE = "\033[34m"
FG_MAGENTA = "\033[35m"
FG_CYAN = "\033[36m"


class Quit(Exception):
    """The user asked to leave the agent (/quit, EOF)."""


def is_tty(stream=None) -> bool:
    try:
        return (stream or sys.stdout).isatty()
    except Exception:
        return False


def use_color() -> bool:
    return is_tty() and not os.environ.get("NO_COLOR")


def color(text: str, *codes: str) -> str:
    if not use_color():
        return text
    return "".join(codes) + text + RESET


def term_width() -> int:
    try:
        width = shutil.get_terminal_size((80, 20)).columns
    except Exception:
        width = 80
    return max(20, min(120, width))


def hr(char="-") -> str:
    return char * term_width()


class Spinner:
    FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(self, message="", interval=0.1, enabled=None):
        self.message = message
        self.interval = interval
        self.enabled = is_tty() if enabled is None else enabled
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if not self.enabled:
            return self

        def run():
            frames = itertools.cycle(self.FRAMES)
            prefix = color(self.message, FG_CYAN, BOLD) + " " if self.message else ""
            while not self._stop.is_set():
                sys.stdout.write(f"\r{prefix}{color(next(frames), FG_CYAN)} ")
                sys.stdout.flush()
                time.sleep(self.interval)
            sys.stdout.write("\r" + " " * term_width() + "\r")
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


def wrap_print(text: str, *codes: str, indent="  ") -> None:
    for paragraph in str(text).splitlines():
        if not paragraph.strip():
            print()
            continue
        for line in textwrap.wrap(paragraph, width=term_width() - len(indent)):
            print(indent + color(line, *codes))


def banner(cwd, task: str, model: str) -> None:
    print(hr("━"))
    print(color(f"Academic Agent — {cwd}", BOLD, FG_BLUE))
    print(color(f"Model: {model}", DIM))
    print(color("Task:", BOLD), task)
    print(hr("━"))


def section(title: str, icon="•", color_code=FG_CYAN) -> None:
    print()
    print(color(f"{icon} {title}", BOLD, color_code))


def warn(text: str) -> None:
    print(color(f"⚠ {text}", BOLD, FG_YELLOW), file=sys.stderr)


last_error = ""  # for the --json result when the run fails before it starts


def error(text: str) -> None:
    global last_error
    last_error = text
    print(color(text, FG_RED), file=sys.stderr)


def dim(text: str) -> None:
    print(color(text, DIM))


def show_diff(diff: str) -> None:
    for line in diff.rstrip("\n").splitlines():
        if line.startswith(("+++", "---")):
            print(color(line, BOLD))
        elif line.startswith("+"):
            print(color(line, FG_GREEN))
        elif line.startswith("-"):
            print(color(line, FG_RED))
        elif line.startswith("@@"):
            print(color(line, FG_CYAN))
        else:
            print(line)


def show_action(index: int, total: int, tool: str, target: str,
                dangerous: str | None = None) -> None:
    label = color(f"[{index}/{total}] {tool}", BOLD, FG_BLUE)
    print(f"{label} {color(target, BOLD)}")
    if dangerous:
        print(color(f"  ⚠ flagged as dangerous: {dangerous}", BOLD, FG_YELLOW))


def show_output_tail(text: str, lines=15) -> None:
    rows = text.rstrip().splitlines()
    if len(rows) > lines:
        dim(f"  … {len(rows) - lines} earlier lines")
        rows = rows[-lines:]
    for row in rows:
        dim("  " + row[:term_width() - 2])


def read_line(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        print()
        raise Quit() from None


def confirm(prompt: str, default=False) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    answer = read_line(f"{prompt} {hint} ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def approval_prompt(tool: str, allow_always: bool) -> str:
    always = f" / [a]lways {tool}" if allow_always else ""
    return (color("Approve? ", BOLD, FG_GREEN)
            + f"[y]es / [n]o{always} / or type a comment to reject: ")


def format_tokens(n: int) -> str:
    return f"{n:,}"


def status_line(prompt_tokens, completion_tokens, total_in, total_out, cost) -> None:
    dim(
        f"tokens {format_tokens(prompt_tokens)} in / "
        f"{format_tokens(completion_tokens)} out · session "
        f"{format_tokens(total_in)} in / {format_tokens(total_out)} out"
    )


def final_screen(message: str, changed: str, run_log: list, total_in: int,
                 total_out: int, cost) -> None:
    section("Agent completion", icon="✅", color_code=FG_GREEN)
    wrap_print(message or "Task completed.")
    print()
    print(color("Files changed:", BOLD, FG_MAGENTA))
    print(changed.rstrip() if changed.strip() else color("  (none)", DIM))
    print(color("Commands run:", BOLD, FG_MAGENTA))
    if not run_log:
        print(color("  (none)", DIM))
    for i, entry in enumerate(run_log, 1):
        code = entry.get("exit_code")
        status = "OK " if code == 0 else f"ERR {code}"
        cmd = entry.get("command", "").strip().replace("\n", " ⏎ ")
        if len(cmd) > 90:
            cmd = cmd[:87] + "…"
        print(f"  {i:2d}. {status}  {cmd}")
    cost_text = f", ~${cost:.4f}" if cost is not None else ""
    print(color("Tokens:", BOLD, FG_MAGENTA),
          f"{format_tokens(total_in)} in / {format_tokens(total_out)} out"
          f"{cost_text}")
