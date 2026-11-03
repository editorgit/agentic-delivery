#!/usr/bin/env python3
"""Snapshot of my work on one repository for the morning brief.

Sources: Jira (my open issues, who waits for whom, blockers, worklogs), GitLab (my open
MRs), git worktrees, tmux sessions and the Claude Code transcripts of those worktrees.
Read-only everywhere. Prints compact sections that Claude turns into the brief.

    collect.py [--repo PATH]     # default: the git repository of the current directory
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(PLUGIN / "lib"), str(PLUGIN / "skills/jira-reader/scripts")]
import delivery  # noqa: E402
from jira import Jira, JiraError, adf_mentions, adf_text, load_env  # noqa: E402

HOME = Path.home()
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
FIELDS = ["summary", "status", "assignee", "parent", "issuelinks", "updated",
          "timeoriginalestimate", "timespent", "timeestimate"]
STALE_DAYS = 2


def sh(*cmd: str, cwd: Path | None = None) -> str:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def fmt_h(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".") + "h"


def short(text: str | None, n: int = 220) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


# --- Jira ---

def group_of(issue: dict, statuses: dict[str, list[str]]) -> str:
    """active / blocked / ready / review / qa / backlog / other, by status name then category."""
    st = issue["fields"]["status"]
    name = st["name"].lower()
    for group in ("blocked", "review", "qa", "backlog"):
        if name in (s.lower() for s in statuses.get(group, [])):
            return group
    category = (st.get("statusCategory") or {}).get("key")
    return {"indeterminate": "active", "new": "ready"}.get(category, "other")


def pending_replies(comments: list[dict]) -> dict[str, tuple[str, dict]]:
    """Who was @mentioned and has not commented since: accountId -> (name, the asking comment).

    Jira has no "waiting for reply" field; a mention without a later comment from that
    person is the closest signal. Comments are expected oldest first.
    """
    pending: dict[str, tuple[str, dict]] = {}
    for c in comments:
        author = (c.get("author") or {}).get("accountId")
        pending.pop(author, None)
        for acc, name in adf_mentions(c.get("body")).items():
            if acc != author:
                pending[acc] = (name, c)
    return pending


def blockers(issue: dict) -> list[str]:
    """Unresolved issues linked as 'is blocked by'."""
    out = []
    for link in issue["fields"].get("issuelinks") or []:
        other = link.get("inwardIssue")
        if link["type"]["name"].lower() == "blocks" and other:
            st = other["fields"]["status"]
            if (st.get("statusCategory") or {}).get("key") != "done":
                out.append(f"blocked by {other['key']} [{st['name']}] {short(other['fields'].get('summary'), 80)}")
    return out


def task_line(i: dict) -> str:
    f = i["fields"]
    est = (f.get("timeoriginalestimate") or 0) / 3600
    spent = (f.get("timespent") or 0) / 3600
    budget = ""
    if est:
        left = est - spent
        budget = f" | estimate {fmt_h(est)}, spent {fmt_h(spent)}, " + (
            f"left {fmt_h(left)}" if left >= 0 else f"OVERRUN {fmt_h(-left)}")
    elif spent:
        budget = f" | no estimate, spent {fmt_h(spent)}"
    return f"{i['key']} [{f['status']['name']}] {short(f.get('summary'), 90)}{budget} | updated {f['updated'][:10]}"


def comment_line(c: dict, n: int = 300) -> str:
    who = (c.get("author") or {}).get("displayName", "?")
    return f"{who} {c['created'][:10]}: {short(adf_text(c.get('body')), n)}"


def section_jira(jira: Jira, me: dict, cfg: dict) -> tuple[list[dict], list[str]]:
    statuses = cfg["jira"]["statuses"]
    issues = jira.search("assignee = currentUser() AND resolution = EMPTY ORDER BY updated DESC", FIELDS)
    groups: dict[str, list[dict]] = {}
    for i in issues:
        groups.setdefault(group_of(i, statuses), []).append(i)

    shown = [i for g in ("active", "blocked", "ready", "review") for i in groups.get(g, [])]
    shown_keys = sorted(i["key"] for i in shown)
    subs: dict[str, list[dict]] = {}
    if shown_keys:
        for s in jira.search(f"parent in ({', '.join(shown_keys)}) AND resolution = EMPTY", FIELDS):
            subs.setdefault(s["fields"]["parent"]["key"], []).append(s)
    nested = {s["key"] for lst in subs.values() for s in lst}

    # My own subtasks are both in `shown` and under their parent: one entry per key.
    with_comments = list({i["key"]: i for i in shown + [s for lst in subs.values() for s in lst]}.values())
    with ThreadPoolExecutor(8) as ex:
        comments = dict(zip((i["key"] for i in with_comments),
                            ex.map(lambda i: _safe(lambda: jira.comments(i["key"]), []), with_comments)))
    pending = {k: pending_replies(v) for k, v in comments.items()}

    my_id = me["accountId"]
    out = [f"## Jira: my open issues ({len(issues)})"]

    waiting_me = [i for i in with_comments if my_id in pending[i["key"]]]
    out.append(f"\n### Waiting for my answer ({len(waiting_me)})")
    for i in waiting_me:
        out.append("- " + task_line(i))
        out.append(f"  asked: {comment_line(pending[i['key']][my_id][1])}")

    def waiting_others(i: dict) -> list[str]:
        return [f"  waiting for an answer from {name}: {comment_line(c, 160)}"
                for acc, (name, c) in pending.get(i["key"], {}).items() if acc != my_id]

    def subtask_lines(i: dict) -> list[str]:
        lst = subs.get(i["key"], [])
        qa = [s for s in lst if group_of(s, statuses) == "qa"]
        lines = []
        for s in lst:
            if s in qa:
                continue
            who = (s["fields"].get("assignee") or {}).get("accountId")
            owner = "" if who == my_id else \
                f" | assignee: {(s['fields'].get('assignee') or {}).get('displayName', 'unassigned')}"
            lines.append("  └ subtask " + task_line(s) + owner)
            lines += ["  " + ln for ln in waiting_others(s)]
        if qa:
            lines.append(f"  └ subtasks in QA: {len(qa)}")
        return lines

    titles = {"active": "In progress", "blocked": "Blocked", "ready": "Ready for development", "review": "In review"}
    for g, title in titles.items():
        top = [i for i in groups.get(g, []) if i["key"] not in nested]
        out.append(f"\n### {title} ({len(top)})")
        for i in top:
            parent = i["fields"].get("parent")
            out.append("- " + task_line(i)
                       + (f"\n  parent: {parent['key']} {short(parent['fields'].get('summary'), 80)}" if parent else ""))
            reasons = blockers(i)
            if g == "blocked" and not reasons and comments.get(i["key"]):
                reasons = [f"last comment {comment_line(comments[i['key']][-1], 220)}"]
            out += ["  " + r for r in reasons]
            out += waiting_others(i)
            out += subtask_lines(i)

    backlog = [i for i in groups.get("backlog", []) if i["key"] not in nested]
    other = groups.get("other", [])
    out.append(f"\n### Other: in QA {len(groups.get('qa', []))}, in backlog {len(backlog)}"
               + (f", other statuses: {', '.join(i['key'] + ' ' + i['fields']['status']['name'] for i in other)}"
                  if other else ""))
    return issues, out


def section_hours(jira: Jira, me: dict) -> list[str]:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    since = monday - timedelta(days=7)
    keys = [i["key"] for i in jira.search(
        f'worklogAuthor = currentUser() AND worklogDate >= "{since:%Y-%m-%d}"', ["summary"])]
    titles: dict[str, str] = {}
    by_day: dict[date, float] = {}
    by_task_week: dict[str, float] = {}
    after_ms = int(datetime.combine(since, datetime.min.time()).timestamp() * 1000)
    with ThreadPoolExecutor(8) as ex:
        logs = dict(zip(keys, ex.map(lambda k: jira.worklogs(k, after_ms), keys)))
    for key, entries in logs.items():
        for w in entries:
            if (w.get("author") or {}).get("accountId") != me["accountId"]:
                continue
            d = datetime.fromisoformat(w["started"][:10]).date()
            if d < since:
                continue
            h = w.get("timeSpentSeconds", 0) / 3600
            by_day[d] = by_day.get(d, 0) + h
            if d >= monday:
                by_task_week[key] = by_task_week.get(key, 0) + h
    if by_task_week:
        for i in jira.search(f"key in ({', '.join(by_task_week)})", ["summary"]):
            titles[i["key"]] = i["fields"]["summary"]
    week = sum(h for d, h in by_day.items() if d >= monday)
    prev = sum(h for d, h in by_day.items() if d < monday)
    out = ["## Hours (Jira worklogs, by work date)",
           f"today {WEEKDAYS[today.weekday()]} {today:%d.%m}: {fmt_h(by_day.get(today, 0))}"
           f" | this week: {fmt_h(week)} | last week: {fmt_h(prev)}"]
    days = [monday + timedelta(days=n) for n in range(7)
            if monday + timedelta(days=n) <= today or by_day.get(monday + timedelta(days=n))]
    out.append("by day: " + ", ".join(f"{WEEKDAYS[d.weekday()]} {d:%d.%m} {fmt_h(by_day.get(d, 0))}" for d in days))
    out.append("by issue this week:")
    out += [f"- {k} {fmt_h(h)} {short(titles.get(k), 70)}" for k, h in sorted(by_task_week.items(), key=lambda x: -x[1])]
    return out


# --- GitLab ---

def gitlab_api(repo: Path) -> str | None:
    if os.environ.get("GITLAB_URL"):
        return os.environ["GITLAB_URL"].rstrip("/") + "/api/v4"
    origin = sh("git", "remote", "get-url", "origin", cwd=repo).strip()
    m = re.match(r"^(?:git@([^:]+):|ssh://git@([^:/]+)(?::\d+)?/|https?://([^/]+)/)", origin)
    return f"https://{next(g for g in m.groups() if g)}/api/v4" if m else None


def section_gitlab(repo: Path) -> list[str]:
    token = os.environ.get("GITLAB_TOKEN")
    api = gitlab_api(repo)
    if not token or not api:
        return ["## GitLab: skipped (no GITLAB_TOKEN or no GitLab origin)"]
    ctx = ssl._create_unverified_context() if os.environ.get("GITLAB_INSECURE") == "1" else None
    req = urllib.request.Request(api + "/merge_requests?scope=created_by_me&state=opened&per_page=100",
                                 headers={"PRIVATE-TOKEN": token})
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            mrs = json.load(r)
    except (urllib.error.URLError, TimeoutError) as e:
        return [f"## GitLab unreachable ({e})"]
    out = [f"## GitLab: my open MRs ({len(mrs)})"]
    for m in mrs:
        status = m.get("detailed_merge_status")
        # GitLab recomputes detailed_merge_status lazily: after a fix it can still say "conflict".
        if status == "conflict" and not m.get("has_conflicts"):
            status = "status not recomputed, no conflicts"
        out.append(f"- !{m['iid']} {m['source_branch']} -> {m['target_branch']} | {status}"
                   f"{' CONFLICT' if m.get('has_conflicts') else ''} | comments {m.get('user_notes_count', 0)}"
                   f" | updated {m['updated_at'][:10]} | {m['web_url']}")
    return out


# --- worktrees, tmux, Claude transcripts ---

def worktrees(repo: Path) -> list[dict]:
    items, cur = [], {}
    for line in sh("git", "worktree", "list", "--porcelain", cwd=repo).splitlines() + [""]:
        if not line:
            if cur.get("branch"):
                items.append(cur)
            cur = {}
        elif line.startswith("worktree "):
            cur["path"] = line[9:]
        elif line.startswith("branch "):
            cur["branch"] = line[7:].removeprefix("refs/heads/")
    return [w for w in items if "/.worktrees/" in w["path"]]


def tmux_sessions() -> dict[str, dict]:
    fmt = "#{session_name}\t#{pane_current_command}\t#{pane_current_path}"
    res = {}
    for line in sh("tmux", "ls", "-F", fmt).splitlines():
        name, cmd, path = line.split("\t")
        res[path] = {"name": name, "claude": cmd not in {"zsh", "bash", "sh", "fish"}}
    return res


def wt_safety(path: str, branch: str, base: str, key_re: re.Pattern) -> str:
    """What removing the worktree would lose. Branches made by wt have no upstream: compare by name."""
    cwd = Path(path)
    if sh("git", "status", "--porcelain", cwd=cwd).strip():
        return "uncommitted changes"
    merged = subprocess.run(["git", "merge-base", "--is-ancestor", "HEAD", f"origin/{base}"], cwd=cwd,
                            capture_output=True)
    if merged.returncode == 0:
        # A branch without commits of its own is an ancestor of the base too: that is not "merged".
        key = key_re.match(branch)
        subject = sh("git", "log", "-1", "--format=%s", cwd=cwd)
        return f"merged into {base}" if key and key.group(0) in subject else "no commits of its own"
    # GitLab merges with "Merge branch '<branch>' into '<base>'"; the branch SHA itself may not be in base.
    if sh("git", "log", "-1", "--format=%h", "--fixed-strings", f"--grep=Merge branch '{branch}'",
          f"origin/{base}", cwd=cwd).strip():
        return f"merged into {base} (MR)"
    ahead = sh("git", "rev-list", "--count", f"origin/{branch}..HEAD", cwd=cwd).strip()
    if not ahead:
        return "not on origin, not merged"
    return "pushed, not merged" if ahead == "0" else f"{ahead} unpushed commits"


def newest_transcript(path: str) -> Path | None:
    """Newest Claude Code transcript for this directory (~/.claude/projects/<mangled path>)."""
    proj = HOME / ".claude/projects" / re.sub(r"[^a-zA-Z0-9]", "-", path)
    files = list(proj.glob("*.jsonl"))
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def last_assistant_text(transcript: Path) -> tuple[datetime | None, str]:
    """Where the session stopped: Claude's last text and its time, read from the transcript tail.

    The time comes from the message itself: the file mtime moves when a session is resumed.
    """
    with transcript.open("rb") as f:
        f.seek(max(0, transcript.stat().st_size - 2_000_000))
        lines = f.read().decode("utf-8", "replace").splitlines()
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") != "assistant":
            continue
        texts = [c.get("text", "") for c in entry.get("message", {}).get("content", []) if c.get("type") == "text"]
        if any(t.strip() for t in texts):
            ts = entry.get("timestamp")
            when = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().replace(tzinfo=None) if ts else None
            return when, short(" ".join(texts), 350)
    return None, ""


def section_sessions(repo: Path, issues: list[dict], cfg: dict, base: str) -> list[str]:
    key_re = re.compile(cfg["key_pattern"])
    statuses = cfg["jira"]["statuses"]
    by_key = {i["key"]: i for i in issues}
    sessions = tmux_sessions()
    wts = worktrees(repo)
    out = [f"## Worktrees and sessions of {repo.name} ({len(wts)} worktrees)"]
    live, cleanup = [], []
    for w in wts:
        m = key_re.match(w["branch"])
        issue = by_key.get(m.group(0)) if m else None
        in_qa = issue is not None and group_of(issue, statuses) == "qa"
        s = sessions.get(w["path"])
        tr = newest_transcript(w["path"])
        when, said = last_assistant_text(tr) if tr else (None, "")
        sess = (f"tmux {s['name']} ({'claude' if s['claude'] else 'shell'})" if s else "no tmux") + (
            f", last claude message {when:%d.%m %H:%M}" if when else "")
        status = issue["fields"]["status"]["name"] if issue else ("issue closed or not mine" if m else "no issue key")
        line = f"- {w['branch']} | {status} | {sess}"
        # A branch already in the base is finished work, whatever Jira still says.
        merged = issue and not in_qa and wt_safety(w["path"], w["branch"], base, key_re).startswith("merged")
        if issue and not in_qa and not merged:
            age = (datetime.now() - when).days if when else None
            stale = f" [{age} days ago — stale, waits for nothing]" if age is not None and age >= STALE_DAYS else ""
            live.append(line + (f"\n  last from claude{stale}: {said}" if said else ""))
        else:
            if merged:
                line += f" | Jira still says «{status}», branch merged"
            cleanup.append((line, w["path"], w["branch"]))
    out.append(f"\n### On open issues ({len(live)})")
    out += live
    out.append(f"\n### Cleanup candidates: issue in QA, closed, or no key ({len(cleanup)})")
    with ThreadPoolExecutor(8) as ex:
        safety = list(ex.map(lambda c: wt_safety(c[1], c[2], base, key_re), cleanup))
    out += [f"{line} | {s}" for (line, _, _), s in zip(cleanup, safety)]
    return out


def _safe(fn, default):
    try:
        return fn()
    except JiraError:
        return default


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", type=Path, help="repository (default: the one of the current directory)")
    args = ap.parse_args()
    repo = delivery.repo_root(args.repo) if args.repo else delivery.repo_root()
    if not repo:
        print("Error: not in a git repository (pass --repo)", file=sys.stderr)
        return 1
    load_env()
    cfg = delivery.load(repo)
    base = delivery.base_branch(repo, cfg)
    try:
        jira = Jira.from_env()
        me = jira.myself()
    except JiraError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(f"# Snapshot of {repo.name} at {datetime.now():%Y-%m-%d %a %H:%M}, me: {me['displayName']}, base: {base}\n")
    issues, lines = section_jira(jira, me, cfg)
    blocks = [lines]
    for fn in (lambda: section_hours(jira, me), lambda: section_gitlab(repo),
               lambda: section_sessions(repo, issues, cfg, base)):
        try:
            blocks.append(fn())
        except Exception as e:  # one broken source must not kill the whole brief
            blocks.append([f"## Section failed: {e!r}"])
    print("\n\n".join("\n".join(b) for b in blocks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
