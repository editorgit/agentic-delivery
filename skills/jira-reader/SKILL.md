---
name: jira-reader
description: Read a Jira issue — description, comments, subtasks, links, attachments and the Confluence pages it links to — and write the distilled task file `.tracker/<KEY>.md` at the git root. Use when the user names a Jira key and wants it prepared for implementation or review, or pastes a Confluence page URL to read. The purpose is ALWAYS to end with the file written. READ-ONLY against Jira and Confluence.
---

# jira-reader — Jira issue → `.tracker/<KEY>.md`

The goal is a file with the task: the spec as Jira states it, close to verbatim, plus the
essence and acceptance criteria. Reading the issue is the means; **writing the file is
the required outcome**. Only Jira and Confluence are read-only.

Credentials: `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` in the environment or in
`~/.config/agentic-delivery/.env`. Never echo the token.

## Workflow (every step is mandatory)

1. **Fetch.** From this skill's base directory:
   `python3 scripts/fetch_issue.py <KEY>`
   It prints the issue, its comments, subtasks and links, downloads attachments to
   `.tracker/<KEY>/`, and expands the Confluence pages linked from the description,
   comments and remote links (first 5; `DELIVERY_CONFLUENCE_MAX=N` for more). A page with
   no text of its own lists its children: read the relevant one with
   `python3 scripts/fetch_issue.py --page <id>`. A bare Confluence URL from the user is
   answered the same way, with no task file.

   If the output has a `Parent:` line, fetch the parent too (one level up only). A
   subtask often holds just the bug or the rework, while the parent holds the original
   spec, its pages and its attachments.

   Look at downloaded images and PDFs (Read tool): a mockup is part of the spec.

2. **Quote the spec, synthesize the rest.** What the issue, comments and linked pages
   require goes into «Spec from Jira» close to verbatim. The debate around it is not
   dumped: what it settled is quoted as a requirement, what it left open becomes a question.

3. **Collect open questions** where comments conflict or scope and criteria are unclear.

4. **Confirm with the user** (when running directly, not inside the `ticket-reader`
   agent): show the essence, the criteria and the questions; their answers go to
   «Decided in discussion», the spec stays as Jira has it.

5. **Write the file** at `<git root>/.tracker/<KEY>.md` (`git rev-parse --show-toplevel`,
   never relative to the current directory). Create `.tracker/` if needed. Format:

   ```markdown
   # <KEY>: <one-line title>

   ## Essence
   2–4 sentences: what to do and why.

   ## Spec from Jira (do not edit)
   Written only from Jira, by this skill or the ticket-reader agent. Nobody edits it
   afterwards — not the implementer, not the review loop: the reviewer checks the code
   against it.

   ### Issue text
   ### Requirements set in comments
   Every comment that sets, changes or cancels a requirement: author, date, text.
   ### From Confluence and attachments
   The parts that set requirements; the rest is a link under «Links». Omit if none.
   ### From the parent issue <PARENT-KEY>
   Only when there is a parent: the spec this subtask relies on, by the same rules.
   The scope is the subtask's own text; the parent is context to stay consistent with.
   Where they contradict, both stay and the conflict goes to «Open questions».
   ### Acceptance criteria
   - [ ] a checkable criterion that follows from the text above and only from it

   ## Decided in discussion
   The user's answers and decisions made while working. Omit until there are some.
   A decision that departs from the spec is recorded as
   `DEVIATION FROM SPEC (<date>): <what we skip or do otherwise>. Spec: «<quote>». User's answer: «<verbatim>»`;
   without a verbatim answer it stays in «Open questions».

   ## Open questions
   Contradictions and gaps. Omit when there are none.

   ## Links
   - Jira: <KEY> · Parent: <KEY> — <title> · pages, mockups and attachments, one line each
   ```

   **Close to verbatim** means: keep the author's wording of every requirement — no
   paraphrasing, merging, softening or completing. Allowed: dropping greetings and noise,
   fixing markup, a bracketed note next to the original words («[typo? probably the
   admin role]»). A later comment replaces an earlier one only when it says so; otherwise
   both stay and the conflict goes to «Open questions».

   A question whose answer could mean not doing, or doing otherwise, what the spec
   requires is marked «(deviation from spec)» and carries no proposed answer: until the
   user decides, the spec applies.

   Afterwards only «Decided in discussion» and «Open questions» are ever edited. Tell
   the user the path.

## Rules

- The deliverable is ALWAYS the file. Never treat writing it as optional.
- READ-ONLY on Jira and Confluence: the client refuses anything but GET and JQL search.
- Do not invent requirements. If it is undecided, ask; do not guess.
- When comments conflict, the user's answers win.
