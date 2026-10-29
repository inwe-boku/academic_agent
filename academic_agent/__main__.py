"""Command-line interface."""

import argparse
import sys
from pathlib import Path

from . import gitutil, ui
from . import session as sessions
from .api import ApiClient, Config, ConfigError
from .context import DEFAULT_CONTEXT_WINDOW, build_initial_prompt
from .loop import MAX_STEPS, Agent
from .policy import ACCEPT_EDITS, AUTO, DEFAULT, Approver, secret_env_values
from .session import Session


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="academic", description="Academic AI terminal coding agent")
    parser.add_argument("task", nargs="*",
                        help="Task to perform in the current directory")
    parser.add_argument("--accept-edits", action="store_true",
                        help="Apply file changes without asking (commands still ask)")
    parser.add_argument("--auto-approve", action="store_true",
                        help="Apply file changes and run commands without asking; "
                             "commands flagged as dangerous still ask")
    parser.add_argument("--resume", action="store_true",
                        help="Continue the last session of this directory")
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS,
                        help=f"Turns per task before asking (at most {MAX_STEPS})")
    parser.add_argument("--list-models", action="store_true",
                        help="Print the available models and exit")
    parser.add_argument("--sessions", action="store_true",
                        help="List saved sessions and exit")
    parser.add_argument("--clear", action="store_true",
                        help="Delete the saved session of this directory and exit")
    return parser


def _print_retry(exc, delay, attempt, total) -> None:
    ui.clear_line()  # the spinner may be drawing on this line
    ui.warn(f"Transient API error ({exc}); retrying in {delay:g}s "
            f"({attempt}/{total})...")


def _list_sessions() -> int:
    rows = sessions.list_sessions()
    if not rows:
        print("No saved sessions.")
    for row in rows:
        task = row["task"].replace("\n", " ")
        print(f"{row['mtime']}  {row['cwd']}\n    {task[:100]}")
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()

    if args.sessions:
        return _list_sessions()
    if args.clear:
        print("Session deleted." if sessions.clear(root) else "No saved session.")
        return 0

    config = Config.from_env()
    try:
        config.validate(need_model=not args.list_models)
    except ConfigError as exc:
        ui.error(str(exc))
        return 1
    api = ApiClient(config, on_retry=_print_retry)

    if args.list_models:
        try:
            for model in api.models():
                print(f"{model['modelName']}  context={model['contextWindow']}  "
                      f"max_output={model['outputTokenLimit']}")
        except Exception as exc:
            ui.error(f"API error: {exc}")
            return 1
        return 0

    if not 1 <= args.max_steps <= MAX_STEPS:
        parser.error(f"--max-steps must be between 1 and {MAX_STEPS}")
    mode = AUTO if args.auto_approve else ACCEPT_EDITS if args.accept_edits else DEFAULT
    interactive = sys.stdin.isatty()
    if not interactive and mode != AUTO:
        ui.error("stdin is not a terminal; non-interactive runs need --auto-approve.")
        return 2

    git = gitutil.is_repo(root)
    if args.resume:
        session = sessions.load(root)
        if not session or not session.messages:
            ui.error("No saved session found for this directory.")
            return 1
        extra = " ".join(args.task)
        if session.messages[-1]["role"] == "assistant":
            session.messages.append(
                {"role": "user", "content": extra or "Continue with the task."})
        elif extra:
            session.messages[-1]["content"] += f"\n\nUser message: {extra}"
        print(f"Resuming session: {session.task}")
    else:
        if not args.task:
            parser.error("a task is required (or use --resume)")
        task = " ".join(args.task)
        session = Session(cwd=str(root), task=task,
                          messages=[{"role": "user",
                                     "content": build_initial_prompt(root, task)}])
        if git:
            session.start_commit = gitutil.head(root)
            session.dirty_at_start = sorted(gitutil.dirty_files(root))

    ui.banner(root, session.task, config.model)

    if not git:
        ui.warn("No git history: changes cannot be undone. /undo and /diff "
                "are unavailable.")
        if mode != DEFAULT and interactive:
            if not ui.confirm(f"Run in --{mode} mode without git history?"):
                return 1
    elif not args.resume and session.dirty_at_start:
        ui.warn(f"The working tree has uncommitted changes "
                f"({len(session.dirty_at_start)} files). /undo is limited to "
                "files that were clean at start.")
        if interactive and not ui.confirm("Continue?", default=True):
            return 1

    try:
        model_info = api.model_info()
        if model_info is None:
            ui.warn(f"Model {config.model} not found in /models; assuming a "
                    f"{DEFAULT_CONTEXT_WINDOW:,}-token context, no cost estimate.")
    except Exception as exc:
        model_info = None
        ui.warn(f"Could not read model info ({exc}); assuming a "
                f"{DEFAULT_CONTEXT_WINDOW:,}-token context, no cost estimate.")

    agent = Agent(root=root, api=api, session=session, approver=Approver(mode),
                  model_info=model_info, git_enabled=git,
                  max_steps=args.max_steps, secrets=secret_env_values())
    return agent.run()


if __name__ == "__main__":
    raise SystemExit(main())
