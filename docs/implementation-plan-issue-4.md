# Implementation Plan: Issue #4 — Make Academic Agent Faster

## Objective

Sessions are sometimes very slow, independent of how much work the prompt
requires. Find out where the time goes using a small amount of timing data,
then fix the measured bottleneck. Retries, safety prompts, session persistence
and the reply protocol stay unchanged.

## Approach: timing first, then fix

No broad profiling campaign. Add one small, permanent timing record per turn,
reproduce the slowness, and let the numbers decide which fix to make.

## Likely causes visible in the code

These are hypotheses for the timing data to confirm or rule out:

1. **Blocking, non-streamed requests.** `ApiClient._post_once`
   (`academic_agent/api.py`) waits for the full response with `timeout=180`.
   The spinner shows no elapsed time, so a slow model response looks like a
   hang.
2. **Retry backoff.** `RETRY_DELAYS = [2, 5, 15, 30]` adds up to 52 s per
   call, and `Retry-After` can raise that to 300 s per retry. Retries are
   printed to stderr only, where they are easy to miss.
3. **Full history resent every turn.** `Agent._next_reply` sends
   `self.messages` in full. Prompt tokens, and with them server-side latency,
   grow with every step until compaction starts at the budget ratio.
4. **Reasoning models.** `gpt-5`/o-series models (see `supports_json_mode`)
   can take much longer per turn, independent of task size.
5. **JSON-mode fallback.** A 400/422 on `responseFormat` costs one extra
   round-trip, but only once per client because `json_mode` is cached.
6. **Invalid-reply retries.** Up to `MAX_INVALID_RETRIES + 1` full requests
   per turn, each sending the whole history again.
7. **Compaction.** `_ensure_budget` makes an extra, often large, model call.
8. Session save (`session.save`, a full JSON dump every step) and tool
   execution are probably small, but they are measured anyway.

## Phase 1: Timing record (permanent, cheap)

1. In `Agent._chat`, measure wall time per API call: the duration, the number
   of retries and the seconds spent sleeping between them (count them in the
   `on_retry` callback or a wrapper), prompt/completion tokens, and whether
   the call was a normal turn, a correction retry or a compaction.
2. Also time `_ensure_budget`, `_save` and each tool execution.
3. Append one compact entry per step to a new `Session.timings` list. Store
   numbers and categories only, never prompt or output text. Add the field
   with a default so old session files still load (`Session.from_dict`
   already ignores unknown keys).
4. Show a one-line breakdown on the final screen (`ui.final_screen`): total
   API time, retry wait, tool time, local overhead, steps, invalid replies and
   compactions.
5. Add elapsed seconds to the spinner text ("Thinking… 42s") so slow but
   live requests can be told apart from hangs.

Tests: fake HTTP client and fake sleep in `test_api.py`/`test_loop.py`
check that timings are recorded, retry waits are counted and behaviour is
otherwise unchanged.

## Phase 2: Reproduce

1. Run a small fixed task, such as "list the files in tests/ and say how many
   there are", several times with the default model and with one reasoning
   model.
2. Write down the timing breakdown and add a short "Performance" note in
   `docs/troubleshooting.md` that explains how to read it.

## Phase 3: Fix what the numbers show

Pick from these depending on the result. Make one focused change per commit,
each with a regression test:

- **Model latency dominates:** improve progress output (elapsed time; print
  retries through `ui` so they stay visible during the spinner). Document
  model choice in `docs/configuration.md`. If the Academic AI API supports
  streaming, evaluate it as a separate follow-up.
- **Retries dominate:** check the retry classification (e.g. whether a
  timeout after 180 s should be retried with the same timeout) and cap total
  retry wait time.
- **History size dominates:** compact or stub old tool results earlier, for
  example by lowering the budget ratio or stubbing large tool outputs after N
  turns. The existing context guarantees stay in place.
- **Invalid replies dominate:** improve the correction prompt or protocol
  instructions for the affected models.
- **Local overhead (save, compaction, tools):** fix it there, e.g. skip
  redundant saves when nothing changed.

Retries, safety checks, context limits and persistence are not removed just
to make sessions look faster.

## Acceptance criteria

- Each session records a per-step timing breakdown without any prompt or
  output text, and it is shown on the final screen.
- A documented reproduction names the dominant bottleneck.
- At least one fix for that bottleneck is in place, with a regression test.
- The spinner shows elapsed time, and retries stay visible.
- The full test suite passes, and the public CLI and protocol are unchanged
  apart from the new optional timing output.

## Results (2026-10-29)

Measured with the timing record on a 3-file fixture repo (small task) and on
a clone of this repository (read-only "explain the retry path" task):

| Model / task | Wall time | API time | Local overhead |
| --- | --- | --- | --- |
| gpt-4o, small (3 runs) | 2.8–3.9 s | 2.4–3.5 s | ~10 ms |
| gpt-5, small (3 runs) | 7.9–14.1 s | 7.4–13.7 s | ~10 ms |
| gpt-5, realistic (2 runs) | 44–59 s | 43–59 s | ~20 ms |
| gpt-5 + `reasoningEffort=low`, realistic (2 runs) | 25–43 s | 24–42 s | ~10 ms |

- **Dominant bottleneck: model response time.** It grows with output and
  reasoning tokens (one gpt-5 turn with 1,713 output tokens took 20 s) and
  varies a lot between identical runs. Prompt size matters much less. No
  retries happened in these runs.
- Local work (session saves, file tools, compaction) is negligible.
- **Bug found:** `search` passed the agent's stdin to ripgrep. With stdin as
  an open pipe (non-interactive callers, issue #5), ripgrep waited forever,
  and with redirected input it searched stdin. Fixed with
  `stdin=DEVNULL`, plus a regression test.
- **Bug found:** `/models` reports prices per 1,000 tokens, but the cost
  estimate treated them as per token (1000× too high). Fixed.
- **Changes:** per-step timing record and `Time:` summary, elapsed time in
  spinners, retry warnings that no longer collide with the spinner, and
  optional `ACADEMIC_AI_REASONING_EFFORT`.
- **Not reproduced:** an intermittent stall. If it happens again, the
  `Time:` line and the session's `timings` show whether it was API time
  (with or without retries) or something local.
