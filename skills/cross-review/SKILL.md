---
name: cross-review
description: Cross-model review — hands the current branch diff to Codex (OpenAI), a different model than the one that wrote the code, running the `delivery-reviewer` Codex skill against the base branch. Use as step 5 of /delivery:task, or when the user asks to "review this branch with Codex" or for a cross-model review. READ-ONLY: findings come from Codex; Claude applies fixes only when asked.
---

# cross-review — Claude Code writes, Codex reviews

One harness (Claude Code), two models. The model that wrote the diff is the worst judge
of it: it shares its own blind spots. Codex reviews the diff in a read-only sandbox; the
review rules live in the Codex skill `delivery-reviewer` (single source of truth —
do not duplicate its checklist here).

- **Codex** finds issues; it never writes.
- **Claude** orchestrates and applies fixes only on the user's command (or within the
  `/delivery:task` loop, which says which fixes are autonomous).

## Preconditions (fail clearly)

1. `command -v codex` — otherwise stop: the Codex CLI is not installed.
2. `test -f ~/.codex/skills/delivery-reviewer/SKILL.md` — otherwise stop and point to the
   plugin README (copy or link `codex/delivery-reviewer` there). Without it the run
   would be a plain review, not this one.
3. The base exists locally: `BASE=$(python3 <plugin root>/lib/delivery.py base)` and
   `git rev-parse --verify "$BASE"`. Then `git fetch origin "$BASE"` and, if the local
   base is a strict ancestor of `origin/$BASE`, fast-forward it with
   `git update-ref "refs/heads/$BASE" "origin/$BASE"` (never when it has local commits).
   A stale base makes Codex review already-merged code as the branch's own.

`<plugin root>` is two levels above this skill's base directory. If a precondition fails,
say which and stop. Never fall back to Claude's own review silently — that defeats the
cross-model point.

## Run

```bash
REPO="$(git rev-parse --show-toplevel)"
OUT="$(mktemp -t codex-review.XXXXXX)"
codex exec -C "$REPO" -s read-only -o "$OUT" $MODEL_ARGS \
  "Use the delivery-reviewer skill. Review the current diff against base branch $BASE. Check the code against the «Spec from Jira» section of the task file and list every deviation from it in the block «Deviations from the spec». Report findings only; do not modify any files and do not run tests." \
  < /dev/null > "$OUT.log" 2>&1
test -s "$OUT" && cat "$OUT" || grep -E '^ERROR' "$OUT.log" | sort -u
```

`MODEL_ARGS` comes from `review` in `delivery.json`: `-m <codex_model>` and
`-c model_reasoning_effort=<reasoning_effort>` when set; empty otherwise. Pin the model
in config rather than relying on the CLI default, and raise the effort: the default is
too shallow for a review. An unknown model then fails loudly instead of silently
reviewing with something else.

Why each flag:
- `< /dev/null` is required: `codex exec` reads stdin to EOF even with the prompt as an
  argument. Under a background Bash call stdin can be a pipe that never closes, and Codex
  hangs forever without starting.
- `-s read-only` lets Codex run read-only commands (git diff, grep) without approval
  prompts and makes writing impossible — so the run never blocks on a prompt.
- `-o "$OUT"` captures only the final review; stdout carries event noise.
- An empty `$OUT` is a Codex failure, not «no findings»: the reason is in the `ERROR`
  lines of the log. «model at capacity» → rerun later with the same model.

What may go into the prompt: only facts about the diff — untracked files that
`git diff` does not show, what changed since the previous round. Never decisions, their
reasons, or «known / out of scope» notes, and never call the implementer's decisions
agreed: the reviewer reads them in `.tracker/<KEY>.md` and weighs them against the spec.

## Present the result

- Show Codex's findings as they are (`[P1]`/`nit:` severities, `file:line` links).
- They are the OTHER model's opinion. If you think one is wrong, say so and why, but keep
  the original text visible.
- Show the «Deviations from the spec» block as is. Whether a deviation stays is the user's
  call.
- Never commit or push from here.
