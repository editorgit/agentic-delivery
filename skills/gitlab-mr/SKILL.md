---
name: gitlab-mr
description: Open a GitLab merge request for the current branch into the base branch — ready, not a draft, nobody assigned — through git push options, so only a read-only token is needed. If an MR is already open for the branch it only returns the link. Also fetches a bot's AI review of the MR. Use when the user asks to "open the MR", "create a merge request", or at the commit gate of /delivery:task.
---

# gitlab-mr — merge request via push options

## How it works

GitLab creates the MR while processing a push that carries `merge_request.*` options:
`create`, `target`, `title` (no `Draft:` prefix: bots skip drafts),
`remove_source_branch`, `squash`, and `unassign=<own username>` — GitLab always assigns
the pusher to a push-created MR; with `unassign` it recomputes assignees from an empty set.

Push options fire only when the push updates the branch. A fully pushed branch with no MR
has to be deleted on the remote and pushed again.

`GITLAB_TOKEN` (scope `read_api`) serves GET only: the open-MR check, the own username,
the final verification. The API host comes from `origin` (or `GITLAB_URL`). A self-hosted
GitLab with a certificate that does not verify: `GITLAB_INSECURE=1`, as a temporary measure.

## Steps

Scripts are in `scripts/` of this skill's base directory.

1. **Plan** (changes nothing): `scripts/create_mr.sh --plan`
   - an MR is already open → give its link and stop;
   - `push` → the branch is missing on the remote or has unpushed commits;
   - `recreate` → fully pushed; the remote branch must be deleted and pushed again.
2. **Confirm when needed:**
   - `push` publishes commits: run it only if the user asked to push in this request (in
     `/delivery:task` the «yes» at the commit gate counts); otherwise ask once;
   - `recreate` always needs an explicit yes (the remote branch disappears for a moment,
     CI restarts); then pass `--recreate-remote-branch`.
3. **Run:** `scripts/create_mr.sh [--recreate-remote-branch] [--title "<title>"] [--description-file <file>]`
4. **Report:** the MR link and the verification line (draft, target, assignee, merge
   options). Nothing else.

## Title and description

- The title defaults to the last commit subject. Pass `--title` when the branch has
  several commits.
- The description: English, only what the change does and why — the same text as a good
  commit body. Never in it: out-of-scope lists, rejected review findings, deviations from
  the spec, questions to the reviewer. Those go to the user in chat.
- Default: no `--description-file` — for a single-commit branch GitLab takes the commit
  body, so write that body well before committing.

## The bot's AI review

`scripts/fetch_ai_review.sh "<MR URL>" [--sha <commit>]` prints the latest review a bot
(`AI_REVIEW_BOT`, default `code-review-bot`) posted as one general comment: the reviewed
commit, the verdict and the `<findings>` block. Exit 0 found, 3 not posted yet (poll on
it), 1 error. The marker and block format it expects are documented in the script; adapt
them to your bot.

## Hard rules

- Feature branches only, never the base or a protected branch (the script refuses).
- Never force-push. If the local branch diverged from origin, stop and say so.
- GitLab API: GET only. Nothing is posted to the MR. Never echo `GITLAB_TOKEN`.
- Never open a second MR for the same branch.

## Troubleshooting

- Push succeeded, no MR → read the `remote:` lines of the push; GitLab reports option
  errors there.
- HTTP 401 → the token expired.
