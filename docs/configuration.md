# Configuration

## Credentials

Environment variables, or `~/.config/agentic-delivery/.env` (path overridable with
`DELIVERY_ENV`). The environment wins over the file. Template: [`examples/env.example`](../examples/env.example).

| Variable | Used by | Notes |
|---|---|---|
| `JIRA_BASE_URL` | jira-reader, brief | `https://your-team.atlassian.net` |
| `JIRA_EMAIL`, `JIRA_API_TOKEN` | jira-reader, brief | An Atlassian API token. It also reads Confluence. The client sends only GET and JQL search. |
| `GITLAB_TOKEN` | gitlab-mr, brief | Scope `read_api`. MRs are opened through push options, so a write token is not needed. |
| `GITLAB_URL` | gitlab-mr, brief | Default: the host of `origin` |
| `GITLAB_INSECURE=1` | gitlab-mr, brief | A self-hosted instance whose certificate does not verify. Meant as a temporary measure. |
| `AI_REVIEW_BOT` | gitlab-mr | Username of the bot that posts AI reviews (default `code-review-bot`) |
| `DELIVERY_CONFLUENCE_MAX` | jira-reader | How many linked pages to expand (default 5) |

## Project settings — `<repo>/.claude/delivery.json`

Everything is optional. Example: [`examples/delivery.json`](../examples/delivery.json).

| Key | Default | Meaning |
|---|---|---|
| `base_branch` | `origin/HEAD`, then `main`/`master` | The branch MRs target and diffs compare against. `git config wt.base` overrides it, so `wt` and the plugin agree. |
| `key_pattern` | `[A-Z][A-Z0-9]+-\d+` | How issue keys look in branch names and commit subjects |
| `jira.statuses.blocked / review / qa / backlog` | common Jira names | Status names, case-insensitive, that the brief groups. All other statuses go by status category: *In Progress* counts as active, *To Do* as ready. |
| `tests.command` | from `CLAUDE.md` | The command for step 4. `{paths}` becomes the touched test paths. |
| `commit.format` | the style of `git log` | e.g. `{key}: {type}: {summary}` |
| `review.codex_model`, `review.reasoning_effort` | CLI defaults | Pin the reviewer model and raise its effort |
| `review.checklist` | `.claude/review-checklist.md` | Stack-specific review rules for Codex |
| `docs_check` | — | A command that exits non-zero when the docs of touched code are stale. Enables step 9. |
| `ai_review_bot` | — | Enables step 10, verification of a bot's review |

## The task file — `<repo>/.tracker/<KEY>.md`

Written by `jira-reader` and read by everything after it. Add `.tracker/` to `.gitignore`.

```markdown
# PROJ-123: one-line title

## Essence                         — 2–4 sentences, written by the reader
## Spec from Jira (do not edit)    — close to verbatim; nobody edits it afterwards
### Issue text
### Requirements set in comments
### From Confluence and attachments
### From the parent issue PROJ-100
### Acceptance criteria
## Decided in discussion           — the user's answers; deviations need a verbatim quote
## Open questions
## Links
```

A deviation entry looks like this:

```
DEVIATION FROM SPEC (2026-11-03): CSV only, no XLSX. Spec: «export as CSV and XLSX». User's answer: «only CSV for now, XLSX is a separate issue»
```

Who may write what:

| Section | Written by | Read by |
|---|---|---|
| Spec from Jira | `jira-reader` / `ticket-reader` only | everyone; the reviewer checks code against it |
| Decided in discussion | the implementing session, with the user's answers | the reviewer treats it as claims, not as the task |
| Open questions | reader and implementer | the plan gate |
