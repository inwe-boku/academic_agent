---
name: review-pr
description: review an open GitHub pull request with several sub-agents and post Sourcery-style comments
trigger: \breview\b.{0,40}\b(pr|prs|pull[ -]?requests?)\b|\b(pr|pull[ -]?request)\b.{0,20}\breview\b
---
Goal: a review of ONE pull request, posted on GitHub as a "Reviewer's Guide"
PR comment plus one review with inline comments, in the style of Sourcery.
Never change project files, commit, push, check out branches or fetch. The
only files you write are scratch files in `.academic-review/`, which you
delete at the end.

Dry run: if the task says "dry run", "do not post" or "don't post", do steps
1-6 and stop after writing the files; do not run step 7 and do not delete the
files. Say in the done message where they are.

## 1. Find the PR

- PR number from the task. If none is given, run `gh pr list` and ask the
  user which one (question reply). Never review more than one PR per run
  unless the task names several; then do steps 2-8 per PR.
- First run `gh repo view --json nameWithOwner,defaultBranchRef`, then in ONE
  batch (write OWNER/REPO, N and HEADSHA as literal values into every
  command; never use `$(...)` or shell variables):
  - `gh pr view N --json number,title,body,url,author,baseRefName,headRefName,headRefOid,additions,deletions,files,commits`
  - `mkdir -p .academic-review && gh pr diff N > .academic-review/pr-N.diff && wc -l .academic-review/pr-N.diff`
  - `gh api repos/OWNER/REPO/pulls/N/comments --jq ".[] | {path, line, user: .user.login, body: .body[0:300]}"`
    (existing inline comments; do not repeat what others already raised)
  - `git rev-parse HEAD` and `git cat-file -t HEADSHA` (is the PR head
    commit available locally?)
- The working tree is usually NOT the PR branch. Read changed files at the PR
  head with `git show HEADSHA:path` if the commit is available locally,
  otherwise with
  `gh api "repos/OWNER/REPO/contents/PATH?ref=HEADSHA" -H "Accept: application/vnd.github.raw"`.
  read_file and search show the working tree; use them for unchanged code
  and docs only.

## 2. Understand the project (short)

Read, if present: README.md, CLAUDE.md, AGENTS.md, CONTRIBUTING.md, and the
specs folder (`specs/`, `spec/`, `docs/spec*`): first its index/overview, then
only the spec files the PR touches or names (requirement IDs like "SC-12",
"C4.5" in the PR title/body are pointers; search for them). Note 5-15 facts
that matter for the review: purpose, conventions, contracts, the relevant
requirements in their exact wording.

## 3. Understand the PR

Read the whole diff file (read_file with offset/limit until the end). Write
down, for yourself: what the PR claims to do, what it actually changes per
file, which requirements it should satisfy, and what looks suspicious.

## 4. Delegate to reviewers (one delegate action)

Start these sub-agents in ONE delegate action. Each task must be
self-contained, because sub-agents see nothing of this conversation. Give
every sub-agent the same CONTEXT block, then its perspective:

CONTEXT block (fill in): repository, PR number, title, URL, base branch, head
SHA, the PR description (shortened), the path `.academic-review/pr-N.diff`,
how to read files at the head (`git show HEADSHA:path` or the gh api command
from step 1), the list of changed files, your project facts from step 2, the
paths of the relevant spec files, and the existing review comments to skip.

Perspectives:
1. `correctness`: logic errors, wrong conditions, off-by-one, wrong
   units/signs/indices, unhandled None/empty/NaN, broken control flow, changed
   behaviour for existing callers, exceptions swallowed or not raised.
2. `spec-consistency`: does the code do what the spec, the PR description
   and the docs/docstrings/README say? Requirements claimed but not (or only
   partly) implemented, docs or docstrings that are now wrong, naming or
   config keys that differ between code, docs and spec.
3. `tests-and-risks`: are the changed behaviours tested (including edge
   cases and failure paths)? Tests that cannot fail or test the mock;
   regressions for other code paths; data loss, silent wrong results,
   performance traps (loops over large frames, repeated I/O), security
   (paths, shell, secrets).
4. `design`: duplication with existing helpers (search the code base),
   functions that grew too large, dead code, unused imports/parameters,
   inconsistent patterns, simpler alternatives. Only refactors that clearly
   pay off; no style nits that a formatter would fix.

Add this to every task, verbatim:

  Work efficiently: aim for at most 10 turns. Read the diff once, in
  read_file chunks of 200 lines (offset 1, 201, 401, ...; longer output is
  cut), several chunks in one turn; then batch the reads you need.
  Write all values literally into commands; `$(...)`, pipes and shell
  variables are rejected.

  Review only the changes of this PR (lines added or modified in the diff),
  but read surrounding code, callers and tests to judge them. Report at most
  6 findings, most severe first, and only findings you verified in the code;
  "no findings" is a fine result. For each finding give:
  FINDING
  path: <file path as in the diff>
  line: <line number in the NEW file version, on a line the diff adds or
         changes; for a range give start-end>
  severity: high | medium | low
  kind: bug_risk | security | performance | testing | documentation | design
  title: <short title, max 10 words>
  explanation: <2-5 sentences: what is wrong, when it happens, what follows;
               cite path:line of the evidence>
  fix: <one or two sentences, optionally a short code snippet>
  END

  Severity:
  - high: wrong results, crashes or data loss on realistic input.
  - medium: a bug in a plausible edge case; a spec requirement the PR claims
    but does not meet; docs that contradict the code in a way that leads
    users to wrong usage; new logic that can produce wrong results and has
    no test at all.
  - low: everything else, in particular refactors, duplication, performance
    without a measured hot path, missing tests for simple or already
    indirectly tested code, stale docstrings, naming.
  kind design or performance is low unless it causes a real defect.

## 5. Verify and merge

For every finding from the sub-agents:
- Read the cited code yourself (at the PR head). Drop it if the claim is
  wrong, speculative, already handled elsewhere, or already raised in an
  existing comment.
- Check that `line` is a line on the new side of a diff hunk in
  `.academic-review/pr-N.diff` (count from the `@@ -a,b +c,d @@` header:
  context and `+` lines advance the new line number, `-` lines do not). If
  it is not, move the finding to the overall comments instead.
- Merge duplicates. Keep at most 10 inline comments, most severe first.
- Re-check each severity against the scale in step 4; when in doubt, take
  the lower one. The assessment must match the findings: "Ready to merge"
  only without high or medium findings, "Needs changes" with at least one
  high or medium finding.

## 6. Write the review files

a) `.academic-review/guide-N.md`, the PR comment (write_file):

    ## Review of PR

    <2-4 sentences: what the PR does and how.>

    <Optional, only if it helps: one mermaid sequenceDiagram or flowchart in a
    ```mermaid block for the main changed flow.>

    ### File-Level Changes

    | Change | Details | Files |
    | ------ | ------- | ----- |
    | <change> | <ul><li>detail</li><li>detail</li></ul> | `path`<br/>`path` |

    ---
    <sub>Generated by academic agent (review-pr skill).</sub>

b) `.academic-review/review-N.json` (write_file), the review:

    {
      "commit_id": "<HEADSHA>",
      "event": "COMMENT",
      "body": "<review body>",
      "comments": [
        {"path": "<path>", "line": <end line>, "side": "RIGHT", "body": "<comment>"}
      ]
    }

   For a range add "start_line": <start>, "start_side": "RIGHT". Never use
   "APPROVE" or "REQUEST_CHANGES".

   Review body (Markdown, inside the JSON string):

    Hey - I've found <n> issues<, and left some high level feedback>.

    <If overall comments exist:>
    ### Overall comments
    - <finding that has no valid diff line, or a cross-cutting remark>

    ### Assessment

    **<Ready to merge | Needs changes | Needs a human reviewer>.** <1-2
    sentences: why, and what is at stake if a finding is real.>

    Blocking findings: `<path>:<line>`, ... (or "none")

    <details>
    <summary>Prompt for AI Agents</summary>

    ~~~markdown
    Please address the comments from this code review:

    ## Individual Comments

    ### Comment 1
    <location path="<path>" line_range="<start-end or line>" />
    <issue_to_address>
    **<title>**

    <explanation> <fix>
    </issue_to_address>
    ~~~

    </details>

   Inline comment body:

    **<🔴 High | 🟡 Medium | ⚪ Low> · <kind>: <title>**

    <explanation>

    <fix, and if it is a small concrete change a GitHub suggestion block:>
    ```suggestion
    <replacement for exactly the commented line(s)>
    ```

   Only use a suggestion block if it replaces exactly the commented lines and
   is correct and complete; otherwise describe the fix in words.

c) Validate: `python3 -m json.tool .academic-review/review-N.json > /dev/null && echo valid`.
   Fix the file until it is valid. Write JSON strings with \n for newlines
   and escape double quotes.

## 7. Post (skip in a dry run)

- `gh pr comment N --body-file .academic-review/guide-N.md`
- `gh api repos/OWNER/REPO/pulls/N/reviews --method POST --input .academic-review/review-N.json --jq .html_url`
- If the review POST fails with HTTP 422 ("line must be part of the diff" or
  similar), move the offending comments into the "Overall comments" of the
  body, rewrite the JSON and post again. Never post the review twice: if a
  POST returned a URL, it succeeded.

## 8. Clean up and finish

- Delete the scratch files: `rm .academic-review/pr-N.diff
  .academic-review/guide-N.md .academic-review/review-N.json` and
  `rmdir .academic-review`.
- Done message: PR number and title, links to the posted comment and review
  (or the scratch file paths in a dry run), and one line per inline comment
  (`severity · path:line · title`).
