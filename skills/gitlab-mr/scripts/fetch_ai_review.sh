#!/usr/bin/env bash
# Prints the latest AI review a bot posted on a merge request: the reviewed commit, the
# verdict line and the machine-readable <findings> block. GET only.
#   fetch_ai_review.sh <MR URL> [--sha <commit>]
# Exit 0 — review found (with --sha: a review of that commit); 3 — not posted yet; 1 — error.
#
# Expected bot comment shape (adapt the two regexes below to your bot):
#   <!-- ai-review:<sha> -->  ...  a line with "actionable" and "findings"  ...  <findings>…</findings>
set -euo pipefail

ENV_FILE="${DELIVERY_ENV:-$HOME/.config/agentic-delivery/.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

MR_URL=""
SHA=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --sha) SHA="${2:-}"; shift 2 ;;
    *) MR_URL="$1"; shift ;;
  esac
done

if [[ -z "$MR_URL" ]]; then
  echo "Usage: $0 <merge request URL> [--sha <commit>]" >&2
  exit 1
fi
if [[ -z "${GITLAB_TOKEN:-}" ]]; then
  echo "Error: GITLAB_TOKEN is not set." >&2
  exit 1
fi

MR_URL="$MR_URL" SHA="$SHA" BOT="${AI_REVIEW_BOT:-code-review-bot}" python3 <<'PY'
import json, os, re, ssl, sys, urllib.error, urllib.parse, urllib.request

m = re.match(r"^(https?://[^/]+)/(.+?)/-/merge_requests/(\d+)", os.environ["MR_URL"])
if not m:
    print("Error: cannot parse the MR URL.", file=sys.stderr)
    sys.exit(1)
host, project, iid = m.group(1), urllib.parse.quote(m.group(2), safe=""), m.group(3)
bot, sha = os.environ["BOT"], os.environ["SHA"]
ctx = ssl._create_unverified_context() if os.environ.get("GITLAB_INSECURE") == "1" else None

notes, page = [], 1
while True:
    url = f"{host}/api/v4/projects/{project}/merge_requests/{iid}/notes?per_page=100&page={page}&sort=asc"
    req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": os.environ["GITLAB_TOKEN"]})
    try:
        with urllib.request.urlopen(req, context=ctx) as resp:
            batch = json.load(resp)
    except urllib.error.HTTPError as e:
        print(f"Error: HTTP {e.code}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Error: cannot connect: {e.reason}", file=sys.stderr)
        sys.exit(1)
    notes += batch
    if len(batch) < 100:
        break
    page += 1

reviews = []
for n in notes:
    if n.get("system") or (n.get("author") or {}).get("username") != bot:
        continue
    marker = re.search(r"<!-- ai-review:([0-9a-f]{7,40}) -->", n.get("body") or "")
    if marker:
        reviews.append((marker.group(1), n))

if sha:
    reviews = [r for r in reviews if r[0].startswith(sha) or sha.startswith(r[0])]
if not reviews:
    print("No AI review yet" + (f" for commit {sha[:8]}" if sha else ""))
    sys.exit(3)

reviewed_sha, note = reviews[-1]
body = note["body"]
verdict = next((ln.lstrip("> ").strip() for ln in body.splitlines() if "actionable" in ln and "findings" in ln), "")
findings = re.search(r"<findings>\s*(.*?)\s*</findings>", body, re.S)

print(f"AI review by {bot}: note {note['id']} · commit {reviewed_sha[:8]} · {note['created_at']}")
if verdict:
    print(verdict)
print()
print(findings.group(1) if findings else "(no <findings> block — nothing to verify)")
PY
