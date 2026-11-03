#!/usr/bin/env python3
"""Print a Jira issue with everything that defines the task, for an agent to distill.

    fetch_issue.py PROJ-123              # issue, comments, links, attachments, Confluence pages
    fetch_issue.py --page <url-or-id>    # one Confluence page (and its children if it is empty)

Attachments are downloaded to <git root>/.tracker/<KEY>/ (or --out-dir). Confluence pages
linked from the description, comments and remote links are expanded, the first
DELIVERY_CONFLUENCE_MAX of them (default 5). Read-only: nothing is written to Jira.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jira import Jira, JiraError, adf_text, adf_urls, confluence_page_id, storage_text  # noqa: E402


def repo_root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(out.stdout.strip()) if out.returncode == 0 else Path.cwd()


def person(p: dict | None) -> str:
    return (p or {}).get("displayName") or "unassigned"


def hours(seconds: int | None) -> str:
    return f"{seconds / 3600:.1f}h" if seconds else "-"


def print_page(jira: Jira, page_id: str, depth: int = 0) -> None:
    try:
        page = jira.confluence_page(page_id)
    except JiraError as e:
        print(f"[Confluence {page_id}: not read — {e}]")
        return
    text = storage_text(((page.get("body") or {}).get("storage") or {}).get("value", ""))
    print(f"\n=== Confluence: {page.get('title')} (id {page_id}) ===")
    print(text or "(no text of its own)")
    if not text and depth == 0:
        kids = jira.confluence_children(page_id)
        if kids:
            print("Child pages (read the relevant one with --page <id>):")
            for k in kids:
                print(f"- {k.get('title')} (id {k.get('id')})")


def print_issue(jira: Jira, key: str, out_dir: Path | None) -> int:
    try:
        issue = jira.issue(key)
        comments = jira.comments(key)
        remote = jira.remote_links(key)
    except JiraError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    f = issue["fields"]
    print(f"# {issue['key']}: {f.get('summary')}")
    print(f"Type: {(f.get('issuetype') or {}).get('name')} | Status: {(f.get('status') or {}).get('name')}"
          f" | Priority: {(f.get('priority') or {}).get('name')}")
    print(f"Assignee: {person(f.get('assignee'))} | Reporter: {person(f.get('reporter'))}"
          f" | Created: {(f.get('created') or '')[:10]} | Updated: {(f.get('updated') or '')[:10]}")
    print(f"Estimate: {hours(f.get('timeoriginalestimate'))} | Spent: {hours(f.get('timespent'))}"
          f" | Remaining: {hours(f.get('timeestimate'))}")
    for label, field in (("Labels", "labels"), ("Components", "components"), ("Fix versions", "fixVersions")):
        values = [v if isinstance(v, str) else v.get("name") for v in f.get(field) or []]
        if values:
            print(f"{label}: {', '.join(values)}")
    if f.get("parent"):
        p = f["parent"]
        print(f"Parent: {p['key']} — {(p.get('fields') or {}).get('summary')}")

    print("\n## Description\n")
    print(adf_text(f.get("description")).strip() or "(empty)")

    if f.get("subtasks"):
        print("\n## Subtasks")
        for s in f["subtasks"]:
            print(f"- {s['key']} [{s['fields']['status']['name']}] {s['fields']['summary']}")

    if f.get("issuelinks"):
        print("\n## Linked issues")
        for link in f["issuelinks"]:
            other, rel = (link.get("outwardIssue"), link["type"]["outward"]) if link.get("outwardIssue") \
                else (link.get("inwardIssue"), link["type"]["inward"])
            print(f"- {rel} {other['key']} [{other['fields']['status']['name']}] {other['fields']['summary']}")

    print(f"\n## Comments ({len(comments)})")
    for c in comments:
        print(f"\n--- {person(c.get('author'))}, {c['created'][:16].replace('T', ' ')}")
        print(adf_text(c.get("body")).strip())

    attachments = f.get("attachment") or []
    if attachments:
        dest_dir = out_dir or repo_root() / ".tracker" / issue["key"]
        print(f"\n## Attachments → {dest_dir}")
        for a in attachments:
            try:
                path = jira.download(a["content"], dest_dir / a["filename"])
                print(f"- {path} ({a.get('mimeType')}, {a.get('size')} bytes)")
            except JiraError as e:
                print(f"- {a['filename']}: not downloaded — {e}")

    urls = adf_urls(f.get("description")) + [u for c in comments for u in adf_urls(c.get("body"))]
    urls += [(r.get("object") or {}).get("url", "") for r in remote]
    page_ids = list(dict.fromkeys(pid for pid in map(confluence_page_id, urls) if pid))
    others = [u for u in dict.fromkeys(urls) if u and not confluence_page_id(u)]
    if others:
        print("\n## Other links")
        for u in others:
            print(f"- {u}")
    limit = int(os.environ.get("DELIVERY_CONFLUENCE_MAX", "5"))
    for pid in page_ids[:limit]:
        print_page(jira, pid)
    if len(page_ids) > limit:
        print(f"\n[{len(page_ids) - limit} more Confluence pages not expanded: {', '.join(page_ids[limit:])}]")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("key", nargs="?", help="issue key, e.g. PROJ-123")
    ap.add_argument("--page", help="Confluence page URL or id")
    ap.add_argument("--out-dir", type=Path, help="where attachments go (default <git root>/.tracker/<KEY>)")
    args = ap.parse_args()
    if not args.key and not args.page:
        ap.error("give an issue key or --page")
    try:
        jira = Jira.from_env()
    except JiraError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if args.page:
        pid = args.page if args.page.isdigit() else confluence_page_id(args.page)
        if not pid:
            print(f"Error: no page id in {args.page}", file=sys.stderr)
            return 1
        print_page(jira, pid)
        return 0
    return print_issue(jira, args.key, args.out_dir)


if __name__ == "__main__":
    sys.exit(main())
