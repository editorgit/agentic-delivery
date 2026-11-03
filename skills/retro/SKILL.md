---
name: retro
description: Retrospective of a Claude Code session — reads the transcript, finds what went wrong or was missed (user corrections, rejected or failed tool calls, wasted detours, reviewer findings that were confirmed) and proposes concrete changes to memory, CLAUDE.md, skills, agents or hooks so the same thing does not happen again. Use as the last step of /delivery:task, when the user runs `/delivery:retro`, or asks "what did we miss", "retro this session". Proposes first; writes only what the user approves.
---

# retro — a session → fixes to the process

The goal is not a retelling of the session but a short list of changes after which the
same mistake does not happen again. Every proposal rests on an event in the transcript.
Nothing is written without the user's approval.

## Argument

- none — the current session;
- `prev` — the previous session of the same project directory;
- `<session-id>` or a path to a `.jsonl` — that session.

## Step 1 — Transcript

From this skill's base directory:

```bash
python3 scripts/condense.py [prev|<id>|<path>] > <scratch dir>/session.txt
```

It finds the session directory by CWD (otherwise by the git root) and prints a feed
`[N HH:MM] WHO: text`: user messages (and mid-turn ones), assistant text, tool calls one
line each, errors and denials. Read the whole file, in chunks if large. You need it for
the current session too: after context compaction the early details are gone.

## Step 2 — Where fixes can go

Read what a fix could land in, so you do not propose duplicates:
- the project's memory index `MEMORY.md` and the notes close to the problems found;
- the project's `CLAUDE.md` and `~/.claude/CLAUDE.md`;
- the `SKILL.md` of skills and agents that ran in the session (`TOOL Skill:` / `TOOL Agent:` lines).

## Step 3 — Signals

Walk the feed and list events, each with its `[N]`:

1. **User corrections** — «not like that», «why», «I told you», a re-ask, a denied tool
   call, a mid-turn message that changes course.
2. **Errors and denials** — failed commands, hook and permission denials, repeated
   attempts at the same thing.
3. **Reviewer findings that were confirmed** — Codex rounds, the findings-verifier table.
   For each: why was it not caught while the code was being written?
4. **Wasted work** — needless questions, circles, redos, notes that led astray.
5. **Discoveries** — what the session learned by trial and error that is written nowhere
   (environment, API, data quirks).

## Step 4 — Filter

Keep an event only if all three answers are «yes»:
- **will it recur** in another task? A one-off typo or a network blip — no;
- **would a written rule have changed the outcome** — would an agent that read it first
  have acted differently?
- **is it not written yet** in memory, `CLAUDE.md` or a skill? If it is and did not work,
  the proposal is «rephrase / move up / turn into a check», not «add».

Separately mark memory notes that turned out **wrong or stale** — propose fixing or
deleting them.

## Step 5 — Where to put it

Cheapest place that will work, in this order:
- **a skill or agent** — if the failure is at a step the skill describes;
- **memory** (`feedback` / `reference` / `project`) — a behaviour rule or an environment
  fact; updating a note beats adding a neighbour;
- **the project's `CLAUDE.md`** — only rules invisible from the code that cost money when
  broken; not feature descriptions, not what a linter or review catches;
- **the reviewer's skill** (Codex `delivery-reviewer` or the project checklist) — a class
  of error worth catching every time;
- **a hook or script** — only if the rule keeps being broken despite being written, and
  the check is mechanical.

## Step 6 — Report  ⛔ GATE

One message:

| # | What happened `[N]` | Lesson | Where | Change |
|---|---|---|---|---|

- «What happened» — one line with the event number and a short quote.
- «Change» — the exact text (for memory: the whole note or the changed lines), not «add a
  rule about X».
- Below the table — what was filtered out, one line each with the reason, so it is clear
  nothing was skipped.
- Nothing worth it → say so; do not invent changes for the sake of a report.

Then **stop**: the user picks numbers, edits the text or declines.

## Step 7 — Apply

Only the approved items, in the approved wording: memory per the system prompt's format
and index; skills, agents, `CLAUDE.md` as surgical edits. This skill never touches project
code and never commits. At the end, list the changed files, one line each.
