---
name: task
description: End-to-end delivery pipeline driven by a Jira issue key. Use when the user runs `/delivery:task <KEY>` or asks to take an issue from Jira to a merge request. Orchestrates other skills with three human gates — read the issue into a spec file → plan (GATE: approval) → implement → tests → cross-model review loop with Codex → polish → commit (GATE: one question «Open the MR?») → docs → push / MR → verify a bot's AI review of the MR and fix only confirmed findings → retrospective (GATE: «Run a retro?»).
---

# task — from Jira issue to merge request

A thin ORCHESTRATOR. Each stage is done by another skill or agent of this plugin; this
file only orders them and holds the human gates. Invoked as `/delivery:task <KEY>`.

Project settings come from `<git root>/.claude/delivery.json` (see the plugin's
`docs/configuration.md`); project rules from the project's `CLAUDE.md` and Claude's
memory for the project. Where this file says «the base», it means the branch printed by
`python3 <plugin root>/lib/delivery.py base`. `<plugin root>` is two levels above this
skill's base directory, which Claude Code shows when the skill loads.

## Preconditions (check first, stop clearly on failure)

1. We are inside a git repository (`git rev-parse --show-toplevel` succeeds).
2. A key was given (in the command or in the current branch name).
3. Never go past a stage whose dependency is missing (Jira access for step 1, Codex for
   step 5 — those skills check it themselves).

## Step 1 — Read the issue

Run the **`ticket-reader`** agent of this plugin (Agent tool, `subagent_type:
"delivery:ticket-reader"`) with `<KEY>` and anything the user wrote alongside the
command. It follows the `jira-reader` skill, writes `<git root>/.tracker/<KEY>.md` and
returns the path, the open questions and anything it could not read.

It is an agent so that the raw thread, Confluence pages and attachments stay in its
context: this session implements from the file. Wait for its result — nothing below
starts without the file. If it wrote nothing (wrong key, no access), say so and stop.

## Step 2 — Plan  ⛔ GATE 1

Read `.tracker/<KEY>.md` and present, in one message:
- the distilled task: essence, acceptance criteria from «Spec from Jira», open
  questions (the agent's and any you found while planning);
- a concrete implementation **plan**;
- **«Deviations from the spec»** — a separate section, never folded into the plan:
  every point where the plan does not do, or does otherwise, what «Spec from Jira»
  requires (including an open question you would answer that way). Per point: the spec
  quote, what you propose instead and why, and a question about that point alone.
  None → «No deviations from the spec».
- **Prior art first.** Before asking about behaviour (who may do X, what is required,
  what happens on edit or payment), find how the closest existing feature in this
  codebase does it and take that as the default. Ask only where the spec contradicts
  it, framed as «Spec: … / Existing behaviour: … / Question», in one numbered list —
  the people answering only see numbered questions.
- **Entry point** — for every piece of new logic name what calls it in production: a
  route, a background job, a CLI command, an event handler. If nothing does, add a
  caller to the plan by default, even when the spec is silent. If the spec hands the
  caller to another issue, check in Jira that it is a real issue with an assignee; if
  not, recommend building the caller here. Either way it is a separate point under
  «Deviations». Code reachable only from tests is an unfinished task.

Then **STOP** and wait. No code before the user approves. A deviation is approved only
by an answer that names it (its number or content); a general «yes» approves the plan,
not the deviations — ask about them again. Until approved, the plan follows the spec.

Record the answers in `.tracker/<KEY>.md` — the reviewer and the verifier read it:
- write only to «Decided in discussion» and «Open questions»; «Essence» and «Spec from
  Jira» are never edited, even when a decision changes what gets built;
- move answered questions from «Open questions» to «Decided in discussion»;
- a deviation is recorded as
  `DEVIATION FROM SPEC (<date>): <what we skip or do otherwise>. Spec: «<quote>». User's answer: «<verbatim>»`.
  Without a verbatim answer it stays in «Open questions»;
- the same holds for deviations that come up later (review loop, step 10).

## Step 3 — Implement

After approval, implement autonomously, following the project's `CLAUDE.md` and the
project rules in memory.

## Step 4 — Tests

Run the relevant tests with the project's test command (`tests.command` in
`delivery.json`, otherwise what `CLAUDE.md` says). Start with the touched files, widen
when sensible. On failure fix and rerun until green. Report failures with the real output.

## Step 5 — Cross-model review

Run the **`cross-review`** skill: Codex reviews the diff against the base, read-only.
What may go into its prompt is defined there — never put decisions into it or call them
agreed.

## Step 6 — Review ↔ fix loop

For each finding:
- fix the **unambiguous** ones autonomously;
- one that changes behaviour, or where the right approach is genuinely unclear → ask
  the user first;
- a **deviation from the spec** without verbatim consent in `.tracker/<KEY>.md` is not
  yours to settle — neither fix it nor explain it away with a session decision: ask as
  in step 2, then follow the spec or record the deviation with the verbatim answer.

After fixing, go back to step 5. Leave the loop when Codex is clean (no findings except
deviations with verbatim consent) or the user says «done». **At most 3 Codex rounds**:
after the third, stop and give the user what is left.

## Step 7 — Polish

Run the **`polish`** skill: comments, test tiers, the project rules from memory that this
diff touches, migration conflicts with the current base. Its edits are part of the diff
shown at the commit gate.

## Step 8 — Commit  ⛔ GATE 2

- Make sure the branch is a feature branch, not the base or a protected one.
- Commit message in English in the repo's style (`commit.format` in `delivery.json`, or
  what `git log` shows), with a body: what changed and why. GitLab takes the MR
  description from it, so it follows the rules of the `gitlab-mr` skill.
- Show `git diff --stat` and the message, then ask ONE question — **«Open the MR?»** —
  with the answers spelled out:
  - **yes** → commit, step 9, then the `gitlab-mr` skill. Its script pushes together with
    the MR options, so do NOT `git push` first: the branch would be up to date and
    GitLab would not create the MR;
  - **commit and push** → commit, step 9, `git push -u origin <branch>`, no MR;
  - **commit only** → commit, step 9, nothing is pushed;
  - **no** → nothing is committed; wait.
- That answer covers the code commit, the docs commit and the push — do not ask again
  (the `recreate` case of `gitlab-mr` still needs its own yes). Never force-push.

## Step 9 — Docs

Only when `docs_check` is set in `delivery.json`. Run it after the code commit:
- success → no docs needed; one line and on to the push;
- it lists sections whose docs are stale → update each (with the project's docs skill if
  it has one), commit only the docs as `<KEY>: docs: <sections>`, rerun the check;
- the check itself is broken → show the output and stop before the push.

## Step 10 — The bot's AI review of the MR

Only when an MR exists and `ai_review_bot` is set in `delivery.json`. A bot posts an AI
review of the pushed commit. Its findings come from another model, are unverified
hypotheses and are often wrong: verify every one, fix only the real ones.

1. **Wait for the review of HEAD** as a background command, so the session is notified:
   ```bash
   S=<gitlab-mr skill dir>/scripts/fetch_ai_review.sh
   for i in $(seq 1 20); do "$S" "<MR URL>" --sha "$(git rev-parse HEAD)"; rc=$?; [ "$rc" -eq 3 ] || exit "$rc"; sleep 60; done; exit 3
   ```
   Exit 0 prints the verdict and the `<findings>` block; exit 3 after ~20 min → the bot
   has not posted; tell the user and stop. Exit 1 is an error, not «not yet».
2. **Verify in a fresh context**: run the **`findings-verifier`** agent
   (`subagent_type: "delivery:findings-verifier"`) with the MR URL, the HEAD sha, `<KEY>`,
   `<plugin root>` and every decision the user made in this session that
   `.tracker/<KEY>.md` lacks. It
   does not see this conversation. It returns `ID | status | evidence | action`. It runs
   separately because this session wrote the code and should not judge findings against it.
3. **Report** its table as returned. If you disagree with a status, say so under it.
4. **Fix only `confirmed`** — minimal fix, step 4 tests, `polish` on the fix, step 9 if
   configured. `blocked`, or a fix that changes behaviour → ask first. A `confirmed`
   finding that turns out not real once you are in the code → stop and say so.
5. **Commit / push** as a new commit. The step 8 answer does not carry over: show the
   diff and ask «Commit and push?»; plain `git push`. Never force-push.
6. **Stop.** The fix commit is not re-reviewed by the bot.

Nothing is written to GitLab in this step: no replies, no resolving, no reactions.

## Step 11 — Retrospective  ⛔ GATE 3

Ask one question — **«Run a retro?»** — and stop. «yes» → run the **`retro`** skill on this
session: it proposes changes to memory, `CLAUDE.md`, skills or agents, and writes only what
the user approves. «no» → the pipeline ends.

## Notes

- Report outcomes faithfully at every stage. Do not claim done until the chosen commit /
  push / MR actually succeeded.
- This skill only orchestrates. Review rules live in the Codex `delivery-reviewer` skill,
  issue reading in `jira-reader` (run by `ticket-reader`), the Codex call in
  `cross-review`, the rules for judging bot findings in `findings-verifier`.
