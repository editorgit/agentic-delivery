"""End-to-end runs of fetch_issue.py and collect.py against a local fake Jira/Confluence
server that answers with the shapes of the Cloud APIs. Checks auth, paging, the read-only
rule and the printed output.
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
AUTH = "Basic " + base64.b64encode(b"bot@example.com:secret").decode()


def adf(*nodes):
    return {"type": "doc", "content": [{"type": "paragraph", "content": list(nodes)}]}


def status(name, cat):
    return {"name": name, "statusCategory": {"key": cat}}


class FakeAtlassian(BaseHTTPRequestHandler):
    base = ""
    posts: list = []

    def log_message(self, *args):
        pass

    def reply(self, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.headers.get("Authorization") != AUTH:
            self.send_response(401)
            self.end_headers()
            return
        path = urlparse(self.path).path
        b = self.base
        routes = {
            "/rest/api/3/myself": {"accountId": "me", "displayName": "Me"},
            "/rest/api/3/issue/PROJ-7": {"key": "PROJ-7", "fields": {
                "summary": "CSV export of orders", "issuetype": {"name": "Story"},
                "status": status("In Progress", "indeterminate"), "priority": {"name": "High"},
                "assignee": {"displayName": "Me"}, "reporter": {"displayName": "Kim"},
                "created": "2026-10-30T09:00:00.000+0000", "updated": "2026-11-02T09:00:00.000+0000",
                "timeoriginalestimate": 14400, "timespent": 3600, "timeestimate": 10800,
                "labels": ["export"], "parent": {"key": "PROJ-1", "fields": {"summary": "Reporting"}},
                "description": adf({"type": "text", "text": "Admins export orders as CSV. Spec: "},
                                   {"type": "inlineCard", "attrs": {"url": f"{b}/wiki/spaces/ENG/pages/42/Export"}}),
                "subtasks": [{"key": "PROJ-8", "fields": {"summary": "Rework", "status": status("To Do", "new")}}],
                "issuelinks": [{"type": {"name": "Blocks", "inward": "is blocked by", "outward": "blocks"},
                                "inwardIssue": {"key": "PROJ-3", "fields": {
                                    "summary": "Orders API", "status": status("Done", "done")}}}],
                "attachment": [{"filename": "mock.png", "content": f"{b}/secure/attachment/1/mock.png",
                                "mimeType": "image/png", "size": 4}],
            }},
            "/rest/api/3/issue/PROJ-7/comment": {"total": 1, "comments": [{
                "author": {"accountId": "kim", "displayName": "Kim"}, "created": "2026-11-01T10:00:00.000+0000",
                "body": adf({"type": "mention", "attrs": {"id": "me", "text": "@Me"}},
                            {"type": "text", "text": " semicolon or comma?"})}]},
            "/rest/api/3/issue/PROJ-7/remotelink": [{"object": {"url": "https://example.com/design"}}],
            "/rest/api/3/issue/PROJ-7/worklog": {"total": 0, "worklogs": []},
            "/wiki/api/v2/pages/42": {"title": "Export", "body": {"storage": {
                "value": "<h2>Columns</h2><ul><li>id</li><li>total</li></ul>"}}},
        }
        if path == "/secure/attachment/1/mock.png":
            return self.reply(b"\x89PNG", "image/png")
        if path in routes:
            return self.reply(routes[path])
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeAtlassian.posts.append((self.path, body))
        if self.path != "/rest/api/3/search/jql":
            self.send_response(405)
            self.end_headers()
            return
        jql = body["jql"]
        issues = []
        if jql.startswith("assignee = currentUser()"):
            issues =[{"key": "PROJ-7", "fields": {
                "summary": "CSV export of orders", "status": status("In Progress", "indeterminate"),
                "updated": "2026-11-02T09:00:00.000+0000", "issuelinks": [],
                "timeoriginalestimate": 14400, "timespent": 3600}}]
        self.reply({"issues": issues, "isLast": True})


class ScriptsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAtlassian)
        FakeAtlassian.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.repo = Path(cls.tmp.name) / "shop"
        subprocess.run(["git", "init", "-q", "-b", "main", str(cls.repo)], check=True)
        cls.env = {**os.environ, "JIRA_BASE_URL": FakeAtlassian.base, "JIRA_EMAIL": "bot@example.com",
                   "JIRA_API_TOKEN": "secret", "DELIVERY_ENV": "/nonexistent", "GITLAB_TOKEN": ""}

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def run_script(self, *args):
        res = subprocess.run([sys.executable, *args], cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout

    def test_fetch_issue(self):
        out = self.run_script(str(ROOT / "skills/jira-reader/scripts/fetch_issue.py"), "PROJ-7")
        self.assertIn("# PROJ-7: CSV export of orders", out)
        self.assertIn("Estimate: 4.0h | Spent: 1.0h | Remaining: 3.0h", out)
        self.assertIn("Parent: PROJ-1 — Reporting", out)
        self.assertIn("Admins export orders as CSV.", out)
        self.assertIn("- is blocked by PROJ-3 [Done] Orders API", out)
        self.assertIn("@Me semicolon or comma?", out)
        self.assertIn("=== Confluence: Export (id 42) ===", out)
        self.assertIn("## Columns", out)
        self.assertIn("- https://example.com/design", out)
        self.assertEqual((self.repo / ".tracker/PROJ-7/mock.png").read_bytes(), b"\x89PNG")

    def test_collect(self):
        FakeAtlassian.posts.clear()
        out = self.run_script(str(ROOT / "skills/brief/scripts/collect.py"), "--repo", str(self.repo))
        self.assertIn("me: Me, base: main", out)
        self.assertIn("### Waiting for my answer (1)\n- PROJ-7", out)
        self.assertIn("left 3h", out)
        self.assertIn("## GitLab: skipped", out)
        self.assertTrue(all(path == "/rest/api/3/search/jql" for path, _ in FakeAtlassian.posts))


if __name__ == "__main__":
    unittest.main()
