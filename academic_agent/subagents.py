"""Read-only sub-agents started by the delegate tool."""

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .api import ApiError
from .context import HistoryBudget, stub_old_results, truncate_output
from .policy import Policy, readonly_reason
from .protocol import CORRECTION, ProtocolError, parse_reply
from .session import Session, redact
from .tools import Executor, ToolError, describe

SUBAGENT_MAX_STEPS = 15
MAX_INVALID = 3
MAX_REPORT_CHARS = 12_000
READONLY_TOOLS = {"read_file", "list_dir", "search", "run"}

SUBAGENT_PROMPT = r"""
You are a read-only sub-agent of a terminal coding agent. You work on one task
in the user's project (the project root is the current working directory) and
report to the main agent, which only sees your final report.

Reply with exactly ONE JSON object per turn and nothing else. Two forms:

  {"type": "actions", "reason": "why", "actions": [<action>, ...]}
  {"type": "done", "message": "your complete final report"}

Actions (paths are relative to the project root):

  {"tool": "read_file", "path": "src/a.py", "offset": 1, "limit": 200}
  {"tool": "list_dir",  "path": ".", "depth": 2}
  {"tool": "search",    "pattern": "regex", "path": "src", "glob": "*.py"}
  {"tool": "run",       "command": "git show abc123:src/a.py"}
      Only single read-only commands: git show/diff/log/blame/ls-files/
      ls-tree/cat-file/rev-parse/merge-base/grep/status, and gh pr view/diff/
      list/checks, issue view/list, repo view, api (GET only). No pipes,
      redirects, $ or command chains.

Rules:
1. You cannot change files and cannot ask the user. Decide yourself and
   mention open questions in your report.
2. You have at most {max_steps} turns. Put several actions in one turn.
3. Base every statement on code or text you have read; cite path:line.
4. Finish with "done". The message is your complete report, in the format
   your task asks for.
"""


@dataclass
class SubagentResult:
    name: str
    report: str
    ok: bool = True
    steps: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class Subagent:
    def __init__(self, name: str, task: str, *, api, root: Path,
                 context_window: int | None = None,
                 max_steps: int = SUBAGENT_MAX_STEPS, secrets=(),
                 log: Callable[[str], None] = print,
                 stop: threading.Event | None = None):
        self.name = name
        self.task = task
        self.api = api
        self.root = Path(root).resolve()
        self.max_steps = max_steps
        self.secrets = list(secrets)
        self.log = log
        self.stop = stop or threading.Event()
        self.budget = HistoryBudget(context_window)
        self.executor = Executor(Policy(self.root),
                                 Session(cwd=str(self.root), task=task),
                                 secrets=self.secrets)
        self.result = SubagentResult(name, "")

    def first_message(self) -> str:
        prompt = SUBAGENT_PROMPT.strip().replace("{max_steps}", str(self.max_steps))
        return f"{prompt}\n\nProject root:\n{self.root}\n\nYour task:\n{self.task}"

    def run(self) -> SubagentResult:
        messages = [{"role": "user", "content": self.first_message()}]
        invalid = 0
        while self.result.steps <= self.max_steps:
            if self.stop.is_set():
                return self._finish("Stopped before finishing.", ok=False)
            last = self.result.steps == self.max_steps
            if last:
                messages[-1]["content"] += ("\n\nStep limit reached: reply now "
                                            "with done and your report.")
            if self.budget.over(messages):
                messages = stub_old_results(messages, self.budget)
            try:
                content = self._chat(messages)
            except ApiError as exc:
                return self._finish(f"API error: {exc}", ok=False)
            self.result.steps += 1
            try:
                reply = parse_reply(content)
            except ProtocolError as exc:
                invalid += 1
                if last:  # a plain-text report is fine at this point
                    return self._finish(content)
                if invalid > MAX_INVALID:
                    return self._finish(f"Invalid replies: {exc}", ok=False)
                messages += [{"role": "assistant", "content": content},
                             {"role": "user", "content": CORRECTION.format(error=exc)}]
                continue
            messages.append({"role": "assistant", "content": content})
            if reply.type == "done" or last:
                return self._finish(reply.text or content)
            if reply.type == "question":
                messages.append({"role": "user", "content": (
                    "You cannot ask the user. Decide yourself, or list the "
                    "question in your final report.")})
                continue
            self.log(f"[{self.name}] {reply.reason or describe(reply.actions[0])}")
            messages.append({"role": "user", "content": self._run_actions(reply.actions)})
        return self._finish("No report.", ok=False)

    def _chat(self, messages) -> str:
        result = self.api.chat(messages)
        self.result.prompt_tokens += result.prompt_tokens
        self.result.completion_tokens += result.completion_tokens
        self.budget.record(result.prompt_tokens, len(messages))
        return result.content

    def _finish(self, report: str, ok: bool = True) -> SubagentResult:
        self.result.report = truncate_output(report.strip(), max_lines=400,
                                             max_chars=MAX_REPORT_CHARS)
        self.result.ok = ok
        return self.result

    def _run_actions(self, actions) -> str:
        results = []
        for i, action in enumerate(actions, 1):
            header = f"[{i}] {action.tool} {describe(action)}"
            results.append(f"{header}: {self._run_action(action)}")
        return "\n\n".join(results)

    def _run_action(self, action) -> str:
        if action.tool not in READONLY_TOOLS:
            return f"FAILED\n{action.tool} is not available to sub-agents"
        if action.tool == "run":
            reason = readonly_reason(action.args["command"], self.root)
            if reason:
                return f"FAILED\nnot allowed: {reason}"
        try:
            result = self.executor.prepare(action).execute()
        except (ToolError, OSError) as exc:
            return f"FAILED\n{exc}"
        status = result.status or ("OK" if result.ok else "FAILED")
        body = truncate_output(redact(result.output, self.secrets))
        return status + (f"\n{body}" if body else "")


def run_subagents(agents: list[dict], **kwargs) -> list[SubagentResult]:
    """Run one Subagent per {"name", "task"} in parallel threads.

    On Ctrl+C the remaining sub-agents stop after their current request.
    """
    stop = threading.Event()
    subs = [Subagent(a["name"], a["task"], stop=stop, **kwargs) for a in agents]
    pool = ThreadPoolExecutor(max_workers=len(subs))
    try:
        futures = [pool.submit(s.run) for s in subs]
        return [_result(s, f) for s, f in zip(subs, futures)]
    except KeyboardInterrupt:
        stop.set()
        raise
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _result(sub: Subagent, future) -> SubagentResult:
    try:
        return future.result()
    except Exception as exc:  # a crash in one sub-agent must not stop the others
        sub.result.report = f"Sub-agent crashed: {type(exc).__name__}: {exc}"
        sub.result.ok = False
        return sub.result
