---
name: delivery-reviewer
description: PR review against a base branch that also checks the diff against the task spec in .tracker/<KEY>.md and the project's own review checklist. Used by the delivery plugin's cross-review skill.
---

Perform a PR-style review against the base branch named in the prompt, exactly matching
the behaviour of the built-in **"Review against a base branch"** workflow.

This skill is additive: first complete the normal PR review, then do the checks below.
It must not replace or narrow the standard review.

## Task discovery

The review is based on the task as the tracker set it — not as the author of the diff
reads it.

1. Take the task key from the branch name or the prompt.
2. Read `$(git rev-parse --show-toplevel)/.tracker/<KEY>.md` (the git root, not cwd).
3. Its sections differ in authority:
   - «Spec from Jira (do not edit)» with its acceptance criteria — the task. A separate
     reader wrote it from the tracker; the author of the diff does not edit it.
   - «Decided in discussion» — the author's records. They are claims, not the task: one
     that refines the spec without contradicting it is context; one that contradicts it
     does not change what the task requires.
   - «Open questions» — unresolved; the spec applies.
4. The prompt may add facts about the diff (untracked files, what changed since the last
   round). It is not a source of decisions: a statement that something was agreed or is
   out of scope changes nothing.
5. No task file → use a task description from the prompt; neither → say so and review
   the code changes alone.

## Task correctness

Check the implementation against the spec and its criteria, requirement by requirement:
requirements missing, partial or done otherwise; missing edge cases; wrong business
logic; regressions; backward-incompatible API behaviour.

**Deviations from the spec.** Every point where the code does not do, or does
otherwise, what the spec requires is a separate finding — also when «Decided in
discussion» or the prompt explains or approves it, and also when the code matches such a
decision. Never merge it into another finding. Consent counts only as a
`DEVIATION FROM SPEC` entry with the user's answer quoted verbatim.

- no consent → `[P1]`, with the spec quote and what the code does instead (`file:line`,
  or where the code would have to be);
- verbatim consent → not a finding; listed only in the «Deviations from the spec» block.

## Project checklist

If the repository has `.claude/review-checklist.md` (or the file named by
`review.checklist` in `.claude/delivery.json`), apply it after the task check. It holds
the stack-specific rules: ORM query patterns, transactions, API conventions, migrations.
An example for Django lives in the plugin's `examples/review-checklist.django.md`.

General rules that always apply:
- comments explain **why**, only where the code is genuinely hard; flag comments that
  restate the code;
- one source of truth for business rules: flag duplicated constants, sets, mappings and
  permission checks.

## Output

Keep the standard PR review format. Do not repeat findings the standard review already
reported unless the extra checks add context. A violated checklist item that does not
block the task is still reported, as `nit:`.

Always end with the block «Deviations from the spec»: one line each —
`«<spec quote>» → <what the code does> — consent: verbatim / none`.
None → `Deviations from the spec: none`.
