"""Unit tests for the plugin's scripts. Fixtures follow the shapes of the Jira Cloud REST v3
and Confluence Cloud v2 responses; nothing here talks to a network.

    python3 -m unittest discover -s tests -v
"""

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "lib"), str(ROOT / "skills/jira-reader/scripts"), str(ROOT / "skills/brief/scripts")]

import collect  # noqa: E402
import delivery  # noqa: E402
import jira  # noqa: E402


def text(t, **marks):
    node = {"type": "text", "text": t}
    if "href" in marks:
        node["marks"] = [{"type": "link", "attrs": {"href": marks["href"]}}]
    return node


def mention(acc, name):
    return {"type": "mention", "attrs": {"id": acc, "text": "@" + name}}


def doc(*paragraphs):
    return {"type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": list(p)} for p in paragraphs]}


def comment(acc, name, created, body):
    return {"author": {"accountId": acc, "displayName": name}, "created": created, "body": body}


def issue(key, status, category, summary="s", **fields):
    f = {"summary": summary, "status": {"name": status, "statusCategory": {"key": category}},
         "updated": "2026-11-02T10:00:00.000+0000", "issuelinks": [], **fields}
    return {"key": key, "fields": f}


class AdfTest(unittest.TestCase):
    def test_text_mentions_links_and_blocks(self):
        d = {"type": "doc", "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [text("Goal")]},
            {"type": "paragraph", "content": [mention("a1", "Kim"), text(" please check "),
                                              text("the page", href="https://x.atlassian.net/wiki/spaces/S/pages/42/P"),
                                              {"type": "hardBreak"}, text("thanks")]},
            {"type": "bulletList", "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [text("one")]}]},
                {"type": "listItem", "content": [{"type": "paragraph", "content": [text("two")]}]}]},
            {"type": "codeBlock", "content": [text("x = 1")]},
        ]}
        out = jira.adf_text(d)
        self.assertIn("## Goal\n", out)
        self.assertIn("@Kim please check the page (https://x.atlassian.net/wiki/spaces/S/pages/42/P)\nthanks", out)
        self.assertIn("- one\n- two\n", out)
        self.assertIn("```\nx = 1\n```", out)

    def test_mentions_and_urls(self):
        d = doc([mention("a1", "Kim"), text(" see https://example.com/a and "),
                 {"type": "inlineCard", "attrs": {"url": "https://x.atlassian.net/wiki/spaces/S/pages/7/T"}}])
        self.assertEqual(jira.adf_mentions(d), {"a1": "Kim"})
        self.assertEqual(jira.adf_urls(d), ["https://example.com/a",
                                            "https://x.atlassian.net/wiki/spaces/S/pages/7/T"])

    def test_empty(self):
        self.assertEqual(jira.adf_text(None), "")
        self.assertEqual(jira.adf_mentions(None), {})


class ConfluenceTest(unittest.TestCase):
    def test_page_id(self):
        self.assertEqual(jira.confluence_page_id("https://x.atlassian.net/wiki/spaces/ENG/pages/12345/Spec+v2"), "12345")
        self.assertEqual(jira.confluence_page_id("https://x.atlassian.net/wiki/pages/viewpage.action?pageId=99"), "99")
        self.assertIsNone(jira.confluence_page_id("https://example.com/pages/1"))

    def test_storage_text(self):
        html = "<h2>Rules</h2><p>Only <strong>admins</strong> may edit.</p><ul><li>a</li><li>b</li></ul>" \
               "<table><tr><th>role</th><th>edit</th></tr><tr><td>admin</td><td>yes</td></tr></table>"
        out = jira.storage_text(html)
        self.assertIn("## Rules", out)
        self.assertIn("Only admins may edit.", out)
        self.assertIn("- a\n- b", out)
        self.assertIn("| admin | yes", out)


class ClientTest(unittest.TestCase):
    def test_refuses_writes(self):
        c = jira.Jira("https://x.atlassian.net", "e", "t")
        with self.assertRaises(jira.JiraError):
            c._request("/rest/api/3/issue/PROJ-1/comment", body={"body": "hi"})

    def test_search_follows_next_page_token(self):
        c = jira.Jira("https://x.atlassian.net", "e", "t")
        pages = [{"issues": [{"key": "A-1"}], "nextPageToken": "n2", "isLast": False},
                 {"issues": [{"key": "A-2"}], "isLast": True}]
        sent = []

        def fake(path, params=None, body=None, raw=False):
            sent.append(body)
            return pages[len(sent) - 1]

        c._request = fake
        self.assertEqual([i["key"] for i in c.search("x", ["summary"])], ["A-1", "A-2"])
        self.assertEqual(sent[1]["nextPageToken"], "n2")


class BriefLogicTest(unittest.TestCase):
    statuses = delivery.DEFAULTS["jira"]["statuses"]

    def test_group_of(self):
        self.assertEqual(collect.group_of(issue("A-1", "In Progress", "indeterminate"), self.statuses), "active")
        self.assertEqual(collect.group_of(issue("A-2", "In Review", "indeterminate"), self.statuses), "review")
        self.assertEqual(collect.group_of(issue("A-3", "blocked", "indeterminate"), self.statuses), "blocked")
        self.assertEqual(collect.group_of(issue("A-4", "To Do", "new"), self.statuses), "ready")
        self.assertEqual(collect.group_of(issue("A-5", "Backlog", "new"), self.statuses), "backlog")
        self.assertEqual(collect.group_of(issue("A-6", "Done", "done"), self.statuses), "other")

    def test_pending_replies(self):
        comments = [
            comment("me", "Me", "2026-11-01T09:00", doc([mention("kim", "Kim"), text(" is the limit per day?")])),
            comment("lee", "Lee", "2026-11-01T10:00", doc([mention("me", "Me"), text(" which endpoint?")])),
            comment("kim", "Kim", "2026-11-01T11:00", doc([text("per day, yes")])),
        ]
        pending = collect.pending_replies(comments)
        self.assertEqual(set(pending), {"me"})
        self.assertEqual(pending["me"][1]["author"]["displayName"], "Lee")
        # my own answer clears what was asked of me
        comments.append(comment("me", "Me", "2026-11-01T12:00", doc([text("the export one")])))
        self.assertEqual(collect.pending_replies(comments), {})

    def test_blockers_only_unresolved_inward(self):
        blocked_by = lambda key, cat: {"type": {"name": "Blocks"}, "inwardIssue": {
            "key": key, "fields": {"summary": "dep", "status": {"name": "x", "statusCategory": {"key": cat}}}}}
        i = issue("A-1", "Blocked", "indeterminate", issuelinks=[
            blocked_by("B-1", "indeterminate"), blocked_by("B-2", "done"),
            {"type": {"name": "Blocks"}, "outwardIssue": {"key": "C-1"}}])
        self.assertEqual(len(collect.blockers(i)), 1)
        self.assertIn("B-1", collect.blockers(i)[0])

    def test_task_line_budget(self):
        i = issue("A-1", "In Progress", "indeterminate", summary="Fix export",
                  timeoriginalestimate=7200, timespent=9000)
        self.assertIn("OVERRUN 0.5h", collect.task_line(i))

    def test_section_jira_end_to_end(self):
        me = {"accountId": "me", "displayName": "Me"}
        parent = issue("A-1", "In Progress", "indeterminate", summary="Export")
        sub = issue("A-2", "In Progress", "indeterminate", summary="Export rework",
                    parent={"key": "A-1", "fields": {"summary": "Export"}}, assignee={"accountId": "me"})
        ready = issue("A-3", "To Do", "new", summary="Import")

        class FakeJira:
            def search(self, jql, fields, limit=500):
                return [sub] if jql.startswith("parent in") else [parent, sub, ready]

            def comments(self, key):
                if key == "A-2":
                    return [comment("kim", "Kim", "2026-11-02T08:00:00.000+0000",
                                    doc([mention("me", "Me"), text(" csv or xlsx?")]))]
                return []

        _, lines = collect.section_jira(FakeJira(), me, {"jira": {"statuses": self.statuses}})
        out = "\n".join(lines)
        self.assertIn("### Waiting for my answer (1)\n- A-2", out)
        self.assertIn("asked: Kim 2026-11-02: @Me csv or xlsx?", out)
        # the subtask is nested under its parent, not a card of its own
        self.assertIn("### In progress (1)\n- A-1", out)
        self.assertIn("  └ subtask A-2", out)
        self.assertIn("### Ready for development (1)\n- A-3", out)

    def test_section_hours(self):
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        stamp = lambda d: f"{d:%Y-%m-%d}T09:00:00.000+0000"

        class FakeJira:
            def search(self, jql, fields, limit=500):
                return [{"key": "A-1", "fields": {"summary": "Export"}}]

            def worklogs(self, key, after_ms=None):
                return [
                    {"author": {"accountId": "me"}, "started": stamp(monday), "timeSpentSeconds": 3 * 3600},
                    {"author": {"accountId": "me"}, "started": stamp(monday - timedelta(days=3)), "timeSpentSeconds": 3600},
                    {"author": {"accountId": "kim"}, "started": stamp(monday), "timeSpentSeconds": 7200},
                ]

        out = "\n".join(collect.section_hours(FakeJira(), {"accountId": "me"}))
        self.assertIn("this week: 3h | last week: 1h", out)
        self.assertIn("- A-1 3h Export", out)


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", "-b", "trunk", str(self.repo)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_and_merge(self):
        self.assertEqual(delivery.load(self.repo), delivery.DEFAULTS)
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude/delivery.json").write_text(json.dumps(
            {"base_branch": "develop", "jira": {"statuses": {"qa": ["Testing"]}}}))
        cfg = delivery.load(self.repo)
        self.assertEqual(cfg["jira"]["statuses"]["qa"], ["Testing"])
        self.assertEqual(cfg["jira"]["statuses"]["blocked"], ["Blocked", "On Hold"])
        self.assertEqual(delivery.base_branch(self.repo, cfg), "develop")

    def test_wt_base_wins(self):
        subprocess.run(["git", "-C", str(self.repo), "config", "wt.base", "release/2"], check=True)
        self.assertEqual(delivery.base_branch(self.repo, {"base_branch": "develop"}), "release/2")


if __name__ == "__main__":
    unittest.main()
