"""Project settings for the delivery plugin: <git root>/.claude/delivery.json plus git facts.

Everything is optional; the defaults fit a plain Jira Cloud project with a `main` branch.
See docs/configuration.md for the full schema.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

DEFAULTS = {
    "key_pattern": r"[A-Z][A-Z0-9]+-\d+",
    "jira": {
        "statuses": {
            "blocked": ["Blocked", "On Hold"],
            "review": ["In Review", "Code Review", "Review"],
            "qa": ["Ready for QA", "In QA", "QA", "Testing", "Ready for Test"],
            "backlog": ["Backlog"],
        },
        "hours_per_day": 8,
    },
}


def git(*args: str, cwd: Path | None = None) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def repo_root(start: Path | None = None) -> Path | None:
    top = git("rev-parse", "--show-toplevel", cwd=start)
    return Path(top) if top else None


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(repo: Path) -> dict:
    path = repo / ".claude" / "delivery.json"
    if not path.exists():
        return DEFAULTS
    try:
        return _merge(DEFAULTS, json.loads(path.read_text()))
    except ValueError as e:
        sys.exit(f"{path}: invalid JSON ({e})")


def base_branch(repo: Path, cfg: dict) -> str:
    """git config wt.base -> delivery.json base_branch -> origin/HEAD -> main/master."""
    b = git("config", "--get", "wt.base", cwd=repo) or cfg.get("base_branch", "")
    if b:
        return b
    head = git("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", cwd=repo)
    if head:
        return head.removeprefix("refs/remotes/origin/")
    for c in ("main", "master"):
        ref = subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/remotes/origin/{c}"], cwd=repo)
        if ref.returncode == 0:
            return c
    return "main"


if __name__ == "__main__":
    # `python3 lib/delivery.py base` prints the base branch for shell scripts.
    root = repo_root() or sys.exit("not in a git repository")
    if sys.argv[1:] == ["base"]:
        print(base_branch(root, load(root)))
    else:
        print(json.dumps(load(root), indent=2))
