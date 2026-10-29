"""Turn loop: ask the model, validate, approve and run actions."""

import time
from pathlib import Path

from . import gitutil, ui
from . import session as sessions
from .api import ApiClient, ApiError, ModelInfo
from .context import (HistoryBudget, apply_summary, compaction_request,
                      split_for_compaction, stub_old_results, truncate_output)
from .policy import Approver, Policy, parse_approval
from .protocol import CORRECTION, ProtocolError, parse_reply
from .session import Session, redact
from .tools import Executor, ToolError, ToolResult, describe

MAX_STEPS = 100
MAX_INVALID_RETRIES = 2
MAX_TIMINGS = 500  # per-step timing entries kept in the session
SLASH_COMMANDS = ("/diff", "/undo", "/cost", "/quit")


class InvalidReply(Exception):
    def __init__(self, error: str, raw: str):
        super().__init__(error)
        self.raw = raw


class Agent:
    def __init__(self, *, root: Path, api: ApiClient, session: Session,
                 approver: Approver, model_info: ModelInfo | None = None,
                 git_enabled: bool = True, max_steps: int = MAX_STEPS,
                 secrets=(), executor: Executor | None = None, policy=None,
                 clock=time.monotonic):
        self.root = Path(root).resolve()
        self.api = api
        self.session = session
        self.approver = approver
        self.model_info = model_info
        self.git_enabled = git_enabled
        self.max_steps = max_steps
        self.secrets = list(secrets)
        self.executor = executor or Executor(policy or Policy(self.root), session)
        self.budget = HistoryBudget(model_info.context_window if model_info else None)
        self.clock = clock
        self.timing: dict | None = None  # entry of the current step

    @property
    def messages(self) -> list:
        return self.session.messages

    # ---- entry point -------------------------------------------------------

    def run(self) -> int:
        try:
            return self._run()
        except ui.Quit:
            self._save()
            print("Session kept. Continue with: academic --resume")
            return 0
        except KeyboardInterrupt:
            self._save()
            print()
            print("Interrupted. Session kept. Continue with: academic --resume")
            return 130

    def _run(self) -> int:
        steps = 0
        while True:
            if steps >= self.max_steps:
                if not self._confirm(f"Reached the step limit ({self.max_steps}). "
                                     f"Continue for another {self.max_steps} steps?"):
                    raise ui.Quit()
                steps = 0
            steps += 1
            self._start_timing()

            self._ensure_budget()
            # History ends with a user message here, so it can be resumed as is.
            self._save()

            try:
                reply, raw = self._next_reply()
            except ApiError as exc:
                ui.error(f"API error: {exc}")
                ui.error("Progress is saved. Continue later with: academic --resume")
                if self._confirm("Retry now?", default=True):
                    steps -= 1
                    continue
                return 1
            except InvalidReply as exc:
                ui.error(f"The model sent {MAX_INVALID_RETRIES + 1} invalid "
                         f"replies in a row: {exc}")
                ui.show_output_tail(exc.raw)
                instruction = self.ask_user("Instruction for the agent (empty to stop): ")
                if not instruction.strip():
                    raise ui.Quit()
                self.messages.append({"role": "assistant", "content": exc.raw})
                self.messages.append({"role": "user", "content": instruction})
                continue

            self.messages.append({"role": "assistant", "content": raw})

            if reply.type == "question":
                self._question(reply.text)
            elif reply.type == "done":
                code = self._done(reply.text)
                if code is not None:
                    return code
                steps = 0
            else:
                self._actions(reply)

    # ---- model calls -------------------------------------------------------

    def _chat(self, messages, json_mode=True, record=True):
        start = self.clock()
        try:
            with ui.Spinner("🤖 Thinking with Academic AI...", interval=0.12,
                            show_elapsed=True):
                result = self.api.chat(messages, json_mode=json_mode)
        finally:
            self._add_timing(api_s=self.clock() - start, calls=1,
                             retries=getattr(self.api, "last_retries", 0),
                             retry_wait_s=getattr(self.api, "last_retry_wait", 0.0))
        self._add_timing(prompt_tokens=result.prompt_tokens,
                         completion_tokens=result.completion_tokens)
        s = self.session
        s.tokens_in += result.prompt_tokens
        s.tokens_out += result.completion_tokens
        cost = (self.model_info.cost(result.prompt_tokens, result.completion_tokens)
                if self.model_info else None)
        s.cost_usd = None if cost is None or s.cost_usd is None else s.cost_usd + cost
        if record:
            self.budget.record(result.prompt_tokens, len(messages))
        ui.status_line(result.prompt_tokens, result.completion_tokens,
                       s.tokens_in, s.tokens_out, s.cost_usd)
        return result

    def _next_reply(self):
        extra = []
        for attempt in range(MAX_INVALID_RETRIES + 1):
            result = self._chat(self.messages + extra)
            try:
                return parse_reply(result.content), result.content
            except ProtocolError as exc:
                if attempt == MAX_INVALID_RETRIES:
                    raise InvalidReply(str(exc), result.content) from None
                ui.dim(f"Invalid reply ({exc}); asking the model to correct it.")
                self._add_timing(invalid=1)
                extra += [
                    {"role": "assistant", "content": result.content},
                    {"role": "user", "content": CORRECTION.format(error=exc)},
                ]

    def _ensure_budget(self) -> None:
        if not self.budget.over(self.messages):
            return
        split = split_for_compaction(self.messages)
        if split is None:
            return
        middle, _ = split
        self._add_timing(compactions=1)
        ui.section("Compacting history", icon="🗜", color_code=ui.DIM)
        request = compaction_request(self.messages[0]["content"], middle,
                                     self.session.task)
        try:
            result = self._chat([{"role": "user", "content": request}],
                                json_mode=False, record=False)
            summary = result.content.strip()
            if not summary:
                raise ApiError("empty summary")
        except ApiError as exc:
            ui.warn(f"Summary failed ({exc}); old tool results are replaced "
                    "by one-line stubs.")
            self.session.messages = stub_old_results(self.messages, self.budget)
        else:
            self.session.messages = apply_summary(self.messages, summary)
            self.session.summaries.append(summary)
            ui.wrap_print(summary, ui.DIM)
        self.budget.reset()

    # ---- reply handlers ----------------------------------------------------

    def _question(self, question: str) -> None:
        ui.section("Question", icon="❓", color_code=ui.FG_MAGENTA)
        ui.wrap_print(question, ui.BOLD)
        answer = self.ask_user(ui.color("Your answer (empty to stop): ",
                                        ui.BOLD, ui.FG_GREEN))
        if not answer.strip():
            raise ui.Quit()
        self.messages.append({"role": "user", "content": answer})

    def _done(self, message: str) -> int | None:
        ui.final_screen(message, self._changed_files(), self.session.run_log,
                        self.session.tokens_in, self.session.tokens_out,
                        self.session.cost_usd, self.session.timings)
        if self._confirm("\nAccept and finish?"):
            sessions.clear(self.session.cwd)
            return 0
        follow = self.ask_user("Next instruction (Enter = let the agent decide): ").strip()
        self.messages.append({
            "role": "user",
            "content": follow or "Continue with follow-up improvements if any. "
                                 "Summarize changes before proposing new actions.",
        })
        return None

    def _actions(self, reply) -> None:
        if reply.reason:
            ui.wrap_print(reply.reason, ui.BOLD)
        total = len(reply.actions)
        results = []
        stopped = rejected = interrupted = False

        for i, action in enumerate(reply.actions, 1):
            header = f"[{i}] {action.tool} {describe(action)}"
            if stopped:
                results.append(f"{header}: SKIPPED (batch stopped)")
                continue
            try:
                prepared = self.executor.prepare(action)
            except ToolError as exc:
                ui.show_action(i, total, action.tool, describe(action))
                ui.error(f"  ✗ {exc}")
                results.append(f"{header}: FAILED\n{exc}")
                stopped = True
                continue

            ui.show_action(i, total, action.tool, prepared.target, prepared.dangerous)
            if action.tool == "run" and "\n" in action.args["command"].strip():
                print(ui.color(action.args["command"].rstrip(), ui.BOLD))
            if prepared.diff and prepared.tier == "write":
                ui.show_diff(prepared.diff)

            if self.approver.needs_prompt(action.tool, bool(prepared.dangerous)):
                decision, comment = self._ask_approval(action.tool,
                                                       not prepared.dangerous)
                if decision != "yes":
                    text = f"{header}: REJECTED by user"
                    if comment:
                        text += f"\nUser comment: {comment}"
                    results.append(text)
                    stopped = rejected = True
                    continue

            result = self._execute(prepared)
            status = result.status or ("OK" if result.ok else "FAILED")
            mark = ui.color("  ✓", ui.FG_GREEN) if result.ok else ui.color("  ✗", ui.FG_RED)
            print(f"{mark} {status}")
            if action.tool == "run" or not result.ok:
                ui.show_output_tail(result.output)
            body = truncate_output(redact(result.output, self.secrets))
            results.append(f"{header}: {status}" + (f"\n{body}" if body else ""))
            if not result.ok:
                stopped = True
            interrupted = interrupted or result.interrupted

        content = "\n\n".join(results)
        if rejected:
            content += "\n\nPropose an alternative, or ask the user if unsure."
        self.messages.append({"role": "user", "content": content})
        if interrupted:
            instruction = self.ask_user(
                "Command interrupted. Instruction for the agent (empty to stop): ")
            if not instruction.strip():
                raise ui.Quit()
            self.messages[-1]["content"] += f"\n\nUser message: {instruction}"

    def _execute(self, prepared) -> ToolResult:
        start = self.clock()
        try:
            if prepared.tier == "exec":
                with ui.Spinner("⏳ Running shell command...", interval=0.1,
                                show_elapsed=True):
                    return prepared.execute()
            return prepared.execute()
        except ToolError as exc:
            return ToolResult(False, str(exc))
        except OSError as exc:
            return ToolResult(False, f"{type(exc).__name__}: {exc}")
        finally:
            self._add_timing(tools_s=self.clock() - start, tools=1)

    def _ask_approval(self, tool: str, allow_always: bool) -> tuple[str, str]:
        while True:
            answer = self.ask_user(ui.approval_prompt(tool, allow_always))
            decision, comment = parse_approval(answer)
            if decision == "always":
                if not allow_always:
                    print("'always' is not available for dangerous commands.")
                    continue
                self.approver.allow_always(tool)
                return "yes", ""
            return decision, comment

    # ---- user input and slash commands -------------------------------------

    def ask_user(self, prompt: str) -> str:
        """Read a line; slash commands are handled here at any prompt."""
        while True:
            text = ui.read_line(prompt)
            command = text.strip()
            if command in SLASH_COMMANDS:
                getattr(self, "cmd_" + command[1:])()
                continue
            return text

    def _confirm(self, prompt: str, default=False) -> bool:
        hint = "[Y/n]" if default else "[y/N]"
        answer = self.ask_user(f"{prompt} {hint} ").strip().lower()
        if not answer:
            return default
        return answer in {"y", "yes"}

    def cmd_quit(self) -> None:
        raise ui.Quit()

    def cmd_cost(self) -> None:
        s = self.session
        cost = f", ~${s.cost_usd:.4f}" if s.cost_usd is not None else ""
        print(f"Tokens: {s.tokens_in:,} in / {s.tokens_out:,} out{cost}")
        if s.timings:
            print(ui.timing_summary(s.timings))

    def _split_touched(self):
        created = sorted(p for p, e in self.session.touched.items() if e.get("created"))
        modified = sorted(p for p, e in self.session.touched.items()
                          if not e.get("created"))
        return created, modified

    def _changed_files(self) -> str:
        if not self.session.touched:
            return ""
        if self.git_enabled:
            return gitutil.status_short(self.root, self.session.touched)
        created, modified = self._split_touched()
        return "\n".join([f"  A {p}" for p in created] + [f"  M {p}" for p in modified])

    def cmd_diff(self) -> None:
        if not self.git_enabled:
            print("/diff is unavailable: not a git repository.")
            return
        created, modified = self._split_touched()
        out = gitutil.diff(self.root, self.session.start_commit, modified)
        for path in created:
            if (self.root / path).is_file():
                out += gitutil.diff_new_file(self.root, path)
        if out.strip():
            ui.show_diff(out)
        else:
            print("No changes by the agent.")

    def cmd_undo(self) -> None:
        if not self.git_enabled:
            print("/undo is unavailable: not a git repository.")
            return
        created, modified = self._split_touched()
        dirty = set(self.session.dirty_at_start)
        start = self.session.start_commit
        restorable = sorted(gitutil.tracked_at(
            self.root, start, [p for p in modified if p not in dirty]))
        skipped = [p for p in modified if p not in restorable]
        if not created and not restorable:
            print("Nothing to undo.")
            for p in skipped:
                print(f"  cannot undo (changed at start or untracked): {p}")
            return
        for p in restorable:
            print(f"  restore {p}")
        for p in created:
            print(f"  delete  {p}")
        for p in skipped:
            print(f"  cannot undo (changed at start or untracked): {p}")
        if not self._confirm("Undo these changes?"):
            return
        if restorable:
            result = gitutil.restore(self.root, start, restorable)
            if result.returncode != 0:
                ui.error(result.stderr.decode(errors="replace").strip())
                return
        for p in created:
            target = (self.root / p).resolve()
            if self.root in target.parents and target.is_file():
                target.unlink()
        for p in restorable + created:
            self.session.touched.pop(p, None)
        self._save()
        print("Undone.")

    def _save(self) -> None:
        start = self.clock()
        try:
            sessions.save(self.session)
        except OSError as exc:
            ui.warn(f"could not save session: {exc}")
        self._add_timing(save_s=self.clock() - start)

    # ---- timing ------------------------------------------------------------

    def _start_timing(self) -> None:
        self.timing = {}
        self.session.timings.append(self.timing)
        del self.session.timings[:-MAX_TIMINGS]

    def _add_timing(self, **values) -> None:
        """Add seconds and counts to the current step's entry."""
        if self.timing is None:
            return
        for key, value in values.items():
            if key.endswith("_s"):
                value = round(self.timing.get(key, 0.0) + value, 3)
            else:
                value = self.timing.get(key, 0) + value
            self.timing[key] = value

