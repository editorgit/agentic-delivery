"""Read-only Jira Cloud + Confluence Cloud client. Standard library only.

Credentials come from the environment, or from ~/.config/agentic-delivery/.env
(override the path with DELIVERY_ENV). Environment variables win over the file.

    JIRA_BASE_URL   https://your-team.atlassian.net
    JIRA_EMAIL      you@example.com
    JIRA_API_TOKEN  an Atlassian API token (the same token works for Confluence)

The only POST this client sends is a JQL search, which reads. Anything else is refused.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ENV_FILE = Path(os.environ.get("DELIVERY_ENV", Path.home() / ".config/agentic-delivery/.env"))
READ_ONLY_POSTS = ("/rest/api/3/search/jql",)


def load_env(path: Path = ENV_FILE) -> None:
    """Fill os.environ from a KEY=VALUE file without overriding what is already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip().removeprefix("export ").strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("'\""))


class JiraError(RuntimeError):
    pass


class Jira:
    def __init__(self, base_url: str, email: str, token: str, timeout: int = 30):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        auth = base64.b64encode(f"{email}:{token}".encode()).decode()
        self.headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}

    @classmethod
    def from_env(cls) -> "Jira":
        load_env()
        missing = [k for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN") if not os.environ.get(k)]
        if missing:
            raise JiraError(f"not set: {', '.join(missing)} (environment or {ENV_FILE})")
        return cls(os.environ["JIRA_BASE_URL"], os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"])

    def _request(self, path: str, params: dict | None = None, body: dict | None = None, raw: bool = False):
        if body is not None and not path.startswith(READ_ONLY_POSTS):
            raise JiraError(f"refusing to POST to {path}: this client is read-only")
        url = path if path.startswith("http") else self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = dict(self.headers)
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body is not None else None,
            method="POST" if body is not None else "GET",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            raise JiraError(f"HTTP {e.code} for {path}") from None
        except urllib.error.URLError as e:
            raise JiraError(f"cannot reach {self.base}: {e.reason}") from None
        return data if raw else json.loads(data or b"null")

    def get(self, path: str, **params):
        return self._request(path, params or None)

    def myself(self) -> dict:
        return self.get("/rest/api/3/myself")

    def issue(self, key: str) -> dict:
        return self.get(f"/rest/api/3/issue/{key}", fields="*all")

    def search(self, jql: str, fields: list[str], limit: int = 500) -> list[dict]:
        issues, token = [], None
        while len(issues) < limit:
            body = {"jql": jql, "fields": fields, "maxResults": min(100, limit - len(issues))}
            if token:
                body["nextPageToken"] = token
            page = self._request("/rest/api/3/search/jql", body=body)
            issues += page.get("issues", [])
            token = page.get("nextPageToken")
            if not token or page.get("isLast", True):
                break
        return issues

    def _paged(self, path: str, key: str, **params) -> list[dict]:
        items, start = [], 0
        while True:
            page = self.get(path, startAt=start, maxResults=100, **params)
            batch = page.get(key, [])
            items += batch
            start += len(batch)
            if not batch or start >= page.get("total", 0):
                return items

    def comments(self, key: str) -> list[dict]:
        """Oldest first."""
        return self._paged(f"/rest/api/3/issue/{key}/comment", "comments", orderBy="created")

    def worklogs(self, key: str, started_after_ms: int | None = None) -> list[dict]:
        extra = {"startedAfter": started_after_ms} if started_after_ms else {}
        return self._paged(f"/rest/api/3/issue/{key}/worklog", "worklogs", **extra)

    def remote_links(self, key: str) -> list[dict]:
        return self.get(f"/rest/api/3/issue/{key}/remotelink")

    def download(self, url: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self._request(url, raw=True))
        return dest

    def confluence_page(self, page_id: str) -> dict:
        return self.get(f"/wiki/api/v2/pages/{page_id}", **{"body-format": "storage"})

    def confluence_children(self, page_id: str) -> list[dict]:
        return self.get(f"/wiki/api/v2/pages/{page_id}/children", limit=50).get("results", [])


# --- Atlassian Document Format (comments and descriptions in API v3) ---

_BLOCKS = {"paragraph", "blockquote", "panel", "rule", "mediaSingle", "mediaGroup", "expand", "decisionList", "taskList"}


def adf_text(node) -> str:
    """Plain text of an ADF document; mentions become @Name, links keep their URL."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_text(n) for n in node)
    t = node.get("type")
    attrs = node.get("attrs") or {}
    if t == "text":
        text = node.get("text", "")
        href = next((m["attrs"]["href"] for m in node.get("marks", []) if m.get("type") == "link"), None)
        return f"{text} ({href})" if href and href != text else text
    if t == "mention":
        name = attrs.get("text") or attrs.get("id", "")
        return name if name.startswith("@") else "@" + name
    if t == "hardBreak":
        return "\n"
    if t in ("inlineCard", "blockCard", "embedCard"):
        return attrs.get("url", "")
    if t == "emoji":
        return attrs.get("text") or attrs.get("shortName", "")
    inner = adf_text(node.get("content", []))
    if t == "heading":
        return "#" * int(attrs.get("level", 1)) + " " + inner + "\n"
    if t == "listItem":
        return "- " + inner.strip() + "\n"
    if t == "codeBlock":
        return "```\n" + inner + "\n```\n"
    if t == "tableRow":
        return " | ".join(adf_text(c).strip() for c in node.get("content", [])) + "\n"
    if t in _BLOCKS:
        return inner.rstrip("\n") + "\n"
    return inner


def adf_mentions(node) -> dict[str, str]:
    """accountId -> display text of everyone mentioned in an ADF document."""
    found: dict[str, str] = {}

    def walk(n):
        if isinstance(n, list):
            for x in n:
                walk(x)
        elif isinstance(n, dict):
            if n.get("type") == "mention":
                a = n.get("attrs") or {}
                if a.get("id"):
                    found[a["id"]] = (a.get("text") or a["id"]).lstrip("@")
            walk(n.get("content", []))

    walk(node)
    return found


_URL_RE = re.compile(r"https?://[^\s)\]>\"']+")


def adf_urls(node) -> list[str]:
    """Every URL in an ADF document: link marks, smart cards and bare URLs in text."""
    urls: list[str] = []

    def walk(n):
        if isinstance(n, list):
            for x in n:
                walk(x)
        elif isinstance(n, dict):
            attrs = n.get("attrs") or {}
            if n.get("type") in ("inlineCard", "blockCard", "embedCard") and attrs.get("url"):
                urls.append(attrs["url"])
            for m in n.get("marks", []):
                if m.get("type") == "link":
                    urls.append(m["attrs"]["href"])
            if n.get("type") == "text":
                urls.extend(_URL_RE.findall(n.get("text", "")))
            walk(n.get("content", []))

    walk(node)
    return list(dict.fromkeys(urls))


def confluence_page_id(url: str) -> str | None:
    """Page id from a Confluence Cloud URL; None for anything else (short /x/ links included)."""
    m = re.search(r"/wiki/spaces/[^/]+/pages/(\d+)", url) or re.search(r"pageId=(\d+)", url)
    return m.group(1) if m else None


# --- Confluence storage format (XHTML) ---

class _StorageText(HTMLParser):
    BREAK_BEFORE = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "blockquote"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BREAK_BEFORE:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append("#" * int(tag[1]) + " ")
        elif tag in ("td", "th"):
            self.parts.append(" | ")
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.parts.append(f"[{href}] ")

    def handle_data(self, data):
        self.parts.append(data)


def storage_text(html: str) -> str:
    p = _StorageText()
    p.feed(html or "")
    text = "".join(p.parts)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+\n", "\n", text)).strip()
