---
name: brief
description: Morning brief and day plan for one repository — my open Jira issues (who waits for my answer, what is in progress and how much estimate is left, what is blocked and by what, what is ready), hours logged today and this week, my open GitLab MRs and conflicts, where each neighbouring Claude session stopped, and worktrees that can be cleaned up. Then it starts the chosen issue in its own tmux session via `wt -d` with `/delivery:task`. Use when the user runs `/delivery:brief`, a scheduled job sends it, or the user asks "what's on my plate", "day plan", "where did the sessions stop", "how many hours logged", "start PROJ-123". READ-ONLY against Jira and GitLab.
---

# brief — the morning brief and the launcher

This skill does not implement anything. It shows the picture, proposes an order, and on
the user's word starts `/delivery:task` in a separate session. It is meant to be the first
thing that runs in the morning, in a session of its own (see «Scheduling» in the plugin
README), so each day starts with an empty context.

## Step 1 — Collect

From this skill's base directory, in the target repository:

```bash
python3 scripts/collect.py --repo <repo>
```

About 10 s. It reads Jira, worklogs, GitLab, `git worktree`, tmux and the Claude
transcripts, and writes nothing. A section that failed prints `## Section failed` or
`GitLab unreachable`: say so in one line and go on.

How to read the output:
- `Waiting for my answer` — someone @mentioned me in a comment and I have not commented
  since. Name who asked and what.
- `waiting for an answer from X` — X was mentioned and has not answered. The issue is
  mine, the next step is X's.
- `Blocked` with `blocked by KEY` — an unresolved «is blocked by» link. Without a link the
  last comment is shown; without either — «no reason in the data».
- `└ subtask` — work on an issue split into subtasks (rework, fixes). The parent stays one
  card; its open subtasks are listed under it. The next step on the card points at the
  subtask that carries the work. `└ subtasks in QA: N` — a count only.
- `parent: KEY` — the issue belongs to a bigger feature: mention it in a few words, e.g.
  to group sibling subtasks in «Ready to take».
- `OVERRUN` — spent above the estimate.
- `last from claude` — the last text that session wrote, with its time: where it stopped
  (waiting for «Open the MR?», a plan approval, an answer, a running test). Marked
  `stale` (2+ days) — the world has moved on: never put it in «Sessions waiting» and never
  retell it as the current state.
- A worktree whose branch is already merged is finished work even if Jira still says «In
  review»: the script moves it to the cleanup list. Do not report it as waiting.

## Step 2 — The brief

One message built around **issues, not sources**: every issue appears **exactly once**, as
one card that merges what is known about it — status and estimate, who waits for whom,
where its session stopped, its MR.

```
**PROJ-430** Order missing from the finance report · In Progress · 0h of 2.3h
→ <the one next step that is mine, imperative: «Answer "yes" to the commit in its session, then reply to Kim»>
  <1–3 short facts that justify it: what the session reports, what was asked and by whom, MR state>
```

The arrow line is the focus: one next action. Facts that do not change it are left out.

Groups, in this order; empty groups are skipped:

1. **Header** — date; hours today / this week / last week.
2. **My move** — the next step is mine: a person waits for my answer, a session waits for
   my decision (commit, MR, plan), an MR conflict, an active issue to continue. Ordered by
   urgency: a person waiting > a session waiting > the rest; inside, least time left first.
3. **Waiting on others** — my issues where the next step is someone else's: one line each
   — key, title, whom we wait for and about what, whom to ping.
4. **Ready to take** — one line each with the estimate.
5. **Hours** — two separate tables: by day (`Day | Hours`, then «Total») and by issue
   (`Issue | Title | Hours this week | Left of estimate`). Overruns in one line below.
6. **Cleanup** — only the count: «N worktrees merged, M with a tmux session — clean up?».
   The list comes when the user says yes (step 4).
7. **Start with** — the first 3 cards of «My move» by key only, a few words why, then
   «Where do we start?».

Issues in review with nothing for me to do, and sessions whose last message is stale, are
not shown. Do not paste the script output. Do not guess what is not in the data.

## Step 3 — Start an issue in its own session

On «take KEY» / «start KEY». If KEY is a parent with an open subtask of mine, the session
is for that subtask (say so); with several, ask which.

1. Branch: the existing worktree branch for KEY from the output, if any; otherwise
   `KEY-<2–3 English words from the title>`, in the style of existing branches. Name it in
   the confirmation line.
2. Run, from the repository:
   ```bash
   cd <repo> && zsh -ic 'wt -d -p "/delivery:task KEY" <branch>'
   ```
   `wt -d` creates the worktree and a tmux session with Claude without attaching; `-p` is
   the new Claude's first message, so the pipeline starts there by itself. If the session
   already exists, `wt` prints «prompt not sent»: tell the user it is running and how to
   attach. Never type into an existing session.
3. Reply in one line: the session name, and that the pipeline's plan gate waits for the
   user there (`tmux attach -t '=<session>'`, or the Claude app via Remote Control).

## Step 4 — Look into a session / clean up

- **Look into a session**: `tmux capture-pane -p -t '=<session>:' -S -80` and report in a
  few lines. Read only: never `send-keys` into another session.
- **Clean up**, only after the user says yes:
  1. Show the list: worktrees marked `merged into …` or `no commits of its own`. A tmux
     session with Claude in it is marked: the conversation stays in `/resume`, the
     session is killed.
  2. Never offer `uncommitted changes`, `N unpushed commits`, `pushed, not merged`,
     `not on origin, not merged`: name them as «not touching» with the reason.
  3. After an explicit yes to the list (all or the named items), per worktree, from the repo:
     ```bash
     tmux kill-session -t '=<session>'      # only if it has one
     git worktree remove <path>             # refuses a dirty worktree — then stop on that one
     git branch -D <branch>                 # safe: the script already checked it is merged
     ```
     Report what was removed. Worktrees left out here are removed later by the nightly `wtgc`.

## Rules

- READ-ONLY against Jira and GitLab: no comments, transitions, worklogs, MR actions.
- Commands that start or remove sessions run only on the user's word in this conversation.
  A scheduled job only produces the brief.
- Never echo tokens.
