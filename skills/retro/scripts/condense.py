#!/usr/bin/env python3
"""Condense a Claude Code session transcript (.jsonl) into an event feed for a retrospective.

Keeps user messages (including ones sent mid-turn), assistant text, tool calls as one
line each, and tool errors/denials. Drops thinking, system attachments and successful
tool output.

    condense.py                  # current (newest) session of the project in CWD
    condense.py prev             # the previous session of the same project
    condense.py <session-id>     # by id, in the project directory of CWD
    condense.py <path.jsonl>     # by path
"""

import json
import os
import re
import subprocess
import sys

PROJECTS = os.path.expanduser("~/.claude/projects")
REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
LIMITS = {"user": 2000, "assistant": 700, "tool": 220, "error": 600}


def encode(path):
    return os.path.join(PROJECTS, re.sub(r"[^a-zA-Z0-9]", "-", path))


def project_dir():
    """Session directory: by the launch CWD, otherwise by the git root."""
    if os.path.isdir(encode(os.getcwd())):
        return encode(os.getcwd())
    try:
        top = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.exit(f"No session directory for {os.getcwd()}")
    return encode(top)


def resolve(arg):
    if arg and arg.endswith(".jsonl"):
        return os.path.expanduser(arg)
    pdir = project_dir()
    if arg and arg != "prev":
        return os.path.join(pdir, arg + ".jsonl")
    files = sorted(
        (os.path.join(pdir, f) for f in os.listdir(pdir) if f.endswith(".jsonl")),
        key=os.path.getmtime,
        reverse=True,
    )
    index = 1 if arg == "prev" else 0
    if len(files) <= index:
        sys.exit(f"No session in {pdir}")
    return files[index]


def clip(text, kind):
    text = REMINDER_RE.sub("", text).strip()
    limit = LIMITS[kind]
    return text if len(text) <= limit else text[:limit] + f" …[+{len(text) - limit}]"


def tool_line(item):
    inp = item.get("input") or {}
    brief = (
        inp.get("description")
        or inp.get("command")
        or inp.get("file_path")
        or inp.get("skill")
        or inp.get("prompt")
        or json.dumps(inp, ensure_ascii=False)
    )
    return f"{item.get('name')}: {brief}"


def result_text(item):
    content = item.get("content")
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return str(content or "")


def events(path):
    for line in open(path, encoding="utf-8"):
        d = json.loads(line)
        kind = d.get("type")
        ts = (d.get("timestamp") or "")[11:16]
        if kind == "attachment" and d["attachment"].get("type") == "queued_command":
            yield ts, "USER (mid-turn)", clip(d["attachment"].get("prompt", ""), "user")
            continue
        if kind not in ("user", "assistant") or d.get("isSidechain"):
            continue
        content = (d.get("message") or {}).get("content")
        if isinstance(content, str):
            text = clip(content, "user")
            if text:
                yield ts, "USER", text
            continue
        for item in content or []:
            t = item.get("type")
            if kind == "assistant" and t == "text" and item.get("text", "").strip():
                yield ts, "CLAUDE", clip(item["text"], "assistant")
            elif t == "tool_use":
                yield ts, "TOOL", clip(tool_line(item), "tool")
            elif t == "tool_result" and item.get("is_error"):
                yield ts, "ERROR", clip(result_text(item), "error")
            elif kind == "user" and t == "text" and item.get("text", "").strip():
                yield ts, "USER", clip(item["text"], "user")


def main():
    path = resolve(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"# {path}")
    for n, (ts, who, text) in enumerate(events(path), 1):
        print(f"[{n} {ts}] {who}: {text}")


if __name__ == "__main__":
    main()
