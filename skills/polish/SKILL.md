---
name: polish
description: Final gate before commit, after the task is implemented and reviewed. Four diff-scoped checks — (A) comments and docstrings follow the project's comment rules, (B) tests are in the right tier (DB-heavy tests are not "fast"), (C) the code obeys the project rules stored in Claude's memory that this diff touches, so nothing agreed in an earlier task is quietly dropped, (D) new migrations do not conflict with the current base. Reports and fixes violations. Use as step 7 of /delivery:task, or when the user asks to "polish", "check before commit", "check against memory".
---

# polish — the last self-check before commit

A procedure the main agent runs itself: inspect, report, fix, re-check. No separate
agent and no Codex: this is Claude checking the diff against the project's own rules.

## Where the rules live

- **The project's memory directory** — the path Claude Code gives in the system prompt
  (with `wt`, one directory shared by every worktree of the project). Its `MEMORY.md`
  is the index: one line per rule. These are rules the user taught in earlier tasks;
  most are invisible to linters, which is why they were written down.
- **The project's `CLAUDE.md`** — conventions, test tiers.

Read them at runtime; never recite rules from your own memory. No memory directory →
say so and run only checks B and D.

## Scope — the diff only

```bash
BASE=$(python3 <plugin root>/lib/delivery.py base)   # <plugin root>: two levels above this skill
git diff "$BASE"...HEAD    # committed on the branch
git diff                   # plus uncommitted changes
```

Touch nothing outside the diff.

## Procedure

1. Read each check's source of truth.
2. Collect what the diff introduced (comments for A, tests for B, the rules it touches for C,
   migrations for D).
3. Flag violations with `file:line` and the rule broken.
4. Report them in a short list grouped by check.
5. Fix them (low-risk edits; the user sees them in the diff at the commit gate).
6. Re-check the fixed spots. Nothing found → say so and change nothing.

## Check A — comments and docstrings

Source of truth: the comment rule in memory or `CLAUDE.md`. If the project has none,
use this default and say that you did:

- keep a comment only when it explains non-obvious behaviour the reader needs right
  here, in one line;
- remove: narrative and history («used to be», task keys in code), the rationale of a
  fix (that goes in the commit message — the most common trap), restating what the code
  plainly says, parameter lists that repeat the signature;
- tests: at most a one-line docstring of what is verified, no bug history.

When unsure whether a comment earns its place, remove it.

## Check B — test tiers

Source of truth: the test section of `CLAUDE.md` (e.g. a `fast` marker with a time budget
and an `integration` marker for tests with a real database).

Every test the diff adds or changes in a fast tier must fit its budget. Static signals of
a DB-heavy test: heavy shared fixtures, factory fixtures, bundle fixtures that create many
rows, the test itself creating more than ~20 objects. Move such a test to the slower tier.
When in genuine doubt, run it exactly as CI runs the fast tier.

**Never** raise a timeout or add a per-test timeout to make a slow test pass as fast.

## Check C — the memory rules this diff touches

**Select, do not recite.** On any one task most rules are about things the diff does not
contain; reporting them is noise.

1. Read `MEMORY.md` — one line per rule, cheap to scan.
2. Pick the rules whose subject **appears in the diff**. Ignore the rest silently, and
   ignore categories that cannot be checked against code: process, approvals, how to run
   things, machines, the language of answers.
3. Read the picked notes **in full** — the index line is a hook, not the rule.
4. **Verify the premise.** A note reflects what was true when it was written. If it names
   a field, function, flag or endpoint, confirm it still exists; if not, drop the rule
   and tell the user the note looks stale.
5. Check the diff against each surviving rule.

What «the subject appears in the diff» looks like (examples, not a list to recite):

| the diff contains | the rule to read |
| --- | --- |
| a changed function signature next to a type stub | keep stubs in sync |
| a new endpoint next to a similar one | extend the existing endpoint instead |
| money fields | which unit the project stores |
| a background task in a nested module | how tasks get registered |
| a new translatable string | the catalogue entry CI expects |

Report one line per applied rule with its verdict; do not list rules that did not apply.
Fix unambiguous violations. If honouring a rule changes behaviour, or two rules conflict,
**stop and ask** — never decide that quietly at the last gate before commit.

## Check D — migration conflicts with the current base

Only when the diff adds migration files; otherwise «no migrations» and skip.

A migration chains to the leaf of its app at creation time. If the base got another
migration of the same app since, both share a parent and after the merge the app has two
leaves: migrations fail on deploy. The local tree shows nothing — the other migration is
not in it — so compare with the fresh remote base:

```bash
git fetch -q origin "$BASE"
MB="$(git merge-base HEAD "origin/$BASE")"
OURS="$( (git diff --name-only --diff-filter=A "$MB" -- '*/migrations/*.py'; \
          git ls-files --others --exclude-standard -- '*/migrations/*.py') | sort -u)"
THEIRS="$(git diff --name-only --diff-filter=A "$MB" "origin/$BASE" -- '*/migrations/*.py')"
```

A conflict is any migrations directory present in both lists. Then run the framework's own
check (Django: `makemigrations --check --dry-run` and the loader's `detect_conflicts()`;
Alembic: `alembic heads` shows one head).

**Fixing needs the user's yes**: it starts with merging the base into the branch (never
rebase a pushed branch, never force-push), then renumbering the branch's migration after
the new leaf and pointing its dependency there. Re-run the detection afterwards.

The check sees the base as of now. Other MRs land while this one waits: run check D again
before saying the MR is ready to merge.
