from academic_agent.context import (SUMMARY_MARKER, HistoryBudget, apply_summary,
                                    build_initial_prompt, compaction_request,
                                    estimate_tokens, split_for_compaction,
                                    stub_old_results, stub_result, tree_listing,
                                    truncate_output)


def test_truncate_short_output_unchanged():
    assert truncate_output("a\nb") == "a\nb"


def test_truncate_lines_keeps_head_and_tail():
    text = "\n".join(f"l{i}" for i in range(1000))
    out = truncate_output(text).splitlines()
    assert out[0] == "l0" and out[99] == "l99"
    assert out[100] == "[... 800 lines omitted, use offset/limit ...]"
    assert out[101] == "l900" and out[-1] == "l999"


def test_truncate_large_numbers_use_space_separator():
    text = "\n".join("x" for _ in range(4320))
    assert "[... 4 120 lines omitted" in truncate_output(text)


def test_truncate_chars():
    out = truncate_output("x" * 50_000)
    assert len(out) < 20_100
    assert "30 000 characters omitted" in out


def test_initial_listing_is_limited(project):
    for i in range(400):
        (project / f"f{i:03}.txt").write_text("")
    (project / "a" / "b" / "c" / "d").mkdir(parents=True)
    (project / "a" / "b" / "c" / "d" / "deep.txt").write_text("")
    listing = tree_listing(project, depth=3, max_entries=300)
    lines = listing.splitlines()
    assert len(lines) == 301
    assert lines[:4] == ["a/", "  b/", "    c/  (1 files)", "f000.txt"]
    assert "more files omitted" in lines[-1]
    prompt = build_initial_prompt(project, "do it")
    assert "do it" in prompt and "No AGENTS.md" in prompt


def test_agents_files_included(project):
    (project / "AGENTS.md").write_text("Use tabs.")
    assert "Use tabs." in build_initial_prompt(project, "t")


# ---- history budget -------------------------------------------------------

def conversation(turns, size=100):
    msgs = [{"role": "user", "content": "first"}]
    for i in range(turns):
        msgs.append({"role": "assistant", "content": f"a{i}"})
        msgs.append({"role": "user", "content": f"[1] read_file f{i}.py: OK\n" + "x\n" * size})
    return msgs


def test_estimate_and_budget():
    assert estimate_tokens("x" * 35) == 10
    budget = HistoryBudget(1000)
    assert budget.limit == 700
    msgs = [{"role": "user", "content": "x" * 2100}]  # 600 tokens
    assert not budget.over(msgs)
    msgs.append({"role": "assistant", "content": "x" * 700})  # +200
    assert budget.over(msgs)


def test_budget_uses_reported_prompt_tokens():
    budget = HistoryBudget(1000)
    msgs = [{"role": "user", "content": "short"}]
    budget.record(650, 1)
    msgs.append({"role": "assistant", "content": "x" * 350})  # +100
    assert budget.estimate(msgs) == 750 and budget.over(msgs)
    budget.reset()
    assert not budget.over(msgs)


def test_split_keeps_first_and_last_six_turns():
    msgs = conversation(10)
    middle, tail = split_for_compaction(msgs)
    assert len(tail) == 12 and tail[0]["role"] == "assistant"
    assert middle == msgs[1:9]
    assert split_for_compaction(conversation(6)) is None


def test_apply_summary_alternates_roles():
    msgs = conversation(10)
    new = apply_summary(msgs, "SUMMARY")
    assert len(new) == 13
    assert new[0]["content"] == "first" + SUMMARY_MARKER + "SUMMARY"
    roles = [m["role"] for m in new]
    assert all(a != b for a, b in zip(roles, roles[1:]))
    # a second compaction replaces the earlier summary and passes it on
    newer = apply_summary(new + conversation(8)[1:], "SECOND")
    assert newer[0]["content"].count("## Summary") == 1
    assert newer[0]["content"].endswith("SECOND")
    request = compaction_request(new[0]["content"], newer[1:3], "task")
    assert "Earlier summary:\nSUMMARY" in request


def test_stub_result():
    content = "[1] read_file a.py: OK\nl1\nl2\nl3\n\n[2] run pytest: FAILED (exit code 1)\nboom"
    assert stub_result(content) == (
        "[read_file a.py: 3 lines, omitted]\n[run pytest: 1 lines, omitted]")
    assert stub_result("a user answer") is None


def test_stub_old_results_fallback():
    msgs = conversation(10, size=300)
    budget = HistoryBudget(1000)
    new = stub_old_results(msgs, budget)
    assert new[2]["content"] == "[read_file f0.py: 300 lines, omitted]"
    assert new[-1] == msgs[-1]  # latest turns untouched
    assert len(new) == len(msgs)
