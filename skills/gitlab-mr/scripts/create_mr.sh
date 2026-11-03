#!/usr/bin/env bash
# Opens a GitLab merge request for the current branch through push options, so no write
# token is needed: GitLab creates the MR while processing the push. The read-only token
# (GITLAB_TOKEN, scope read_api) is used for GET only.
#   --plan                    say what would happen, change nothing
#   --recreate-remote-branch  the branch is fully pushed and has no MR: delete it on the
#                             remote and push again (push options fire only on an update)
set -euo pipefail

ENV_FILE="${DELIVERY_ENV:-$HOME/.config/agentic-delivery/.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi
PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

usage() {
  echo "Usage: $0 [--plan] [--recreate-remote-branch] [--title <title>] [--description-file <file>]" >&2
}

PLAN=0
RECREATE=0
TITLE=""
DESCRIPTION_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --plan) PLAN=1; shift ;;
    --recreate-remote-branch) RECREATE=1; shift ;;
    --title) [[ $# -ge 2 ]] || { usage; exit 1; }; TITLE="$2"; shift 2 ;;
    --description-file) [[ $# -ge 2 ]] || { usage; exit 1; }; DESCRIPTION_FILE="$2"; shift 2 ;;
    *) usage; exit 1 ;;
  esac
done

if [[ -z "${GITLAB_TOKEN:-}" ]]; then
  echo "Error: GITLAB_TOKEN is not set (environment or $ENV_FILE)." >&2
  exit 1
fi
if [[ -n "$DESCRIPTION_FILE" && ! -f "$DESCRIPTION_FILE" ]]; then
  echo "Error: no description file $DESCRIPTION_FILE." >&2
  exit 1
fi

BASE="$(python3 "$PLUGIN_ROOT/lib/delivery.py" base)"
BRANCH=$(git rev-parse --abbrev-ref HEAD)
case "$BRANCH" in
  HEAD | main | master | production | release/* | "$BASE")
    echo "Error: an MR is opened only from a feature branch, current: $BRANCH." >&2
    exit 1
    ;;
esac

ORIGIN=$(git remote get-url origin)
PARSED=$(ORIGIN="$ORIGIN" BRANCH="$BRANCH" python3 - <<'PYEOF'
import os, re, sys, urllib.parse
m = re.match(r'^(?:git@([^:]+):|ssh://git@([^:/]+)(?::\d+)?/|https?://([^/]+)/)(.+?)(?:\.git)?$', os.environ["ORIGIN"])
if not m:
    sys.exit(1)
print(m.group(1) or m.group(2) or m.group(3))
print(urllib.parse.quote(m.group(4), safe=""))
print(urllib.parse.quote(os.environ["BRANCH"], safe=""))
PYEOF
) || { echo "Error: cannot parse origin: $ORIGIN" >&2; exit 1; }

GIT_HOST=$(echo "$PARSED" | sed -n '1p')
PROJECT_ENC=$(echo "$PARSED" | sed -n '2p')
BRANCH_ENC=$(echo "$PARSED" | sed -n '3p')
API="${GITLAB_URL:-https://${GIT_HOST}}"
API="${API%/}/api/v4"
CURL_TLS=()
[[ "${GITLAB_INSECURE:-0}" == 1 ]] && CURL_TLS=(-k)

api_get() {
  local resp body code
  # ${arr[@]+...}: an empty array under set -u fails on macOS bash 3.2
  resp=$(curl -sS ${CURL_TLS[@]+"${CURL_TLS[@]}"} -w "\n%{http_code}" -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" "${API}$1")
  body=$(echo "$resp" | sed '$d')
  code=$(echo "$resp" | tail -n1)
  if [[ "$code" != "200" ]]; then
    echo "Error: GET $1 returned HTTP $code" >&2
    echo "$body" >&2
    return 1
  fi
  echo "$body"
}

open_mrs() {
  api_get "/projects/${PROJECT_ENC}/merge_requests?state=opened&source_branch=${BRANCH_ENC}"
}

print_mrs() {
  MRS_JSON="$1" python3 <<'PY'
import json, os, sys
mrs = json.loads(os.environ["MRS_JSON"])
if not mrs:
    sys.exit(1)
for m in mrs:
    assignees = ", ".join(a["username"] for a in m.get("assignees") or []) or "none"
    yes = lambda v: "yes" if v else "no"
    print(f"!{m['iid']} → {m['target_branch']} | draft: {yes(m['draft'])} | assignee: {assignees}"
          f" | delete branch: {yes(m.get('force_remove_source_branch'))} | squash: {yes(m.get('squash'))}")
    print(m["web_url"])
PY
}

EXISTING=$(open_mrs)
if print_mrs "$EXISTING"; then
  echo "An MR is already open for this branch; not creating another one."
  exit 0
fi

USERNAME=$(api_get "/user" | python3 -c 'import json, sys; print(json.load(sys.stdin)["username"])')

LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git ls-remote --heads origin "refs/heads/$BRANCH" | cut -f1)

if [[ -z "$REMOTE_SHA" ]]; then
  ACTION="push"
  NEW_COMMITS=$(git rev-list --count "origin/$BASE..HEAD" 2>/dev/null || echo "?")
elif [[ "$REMOTE_SHA" == "$LOCAL_SHA" ]]; then
  ACTION="recreate"
  NEW_COMMITS=0
else
  git fetch -q origin "$BRANCH"
  if ! git merge-base --is-ancestor "$REMOTE_SHA" "$LOCAL_SHA"; then
    echo "Error: the local branch diverged from origin/$BRANCH; not force-pushing." >&2
    exit 1
  fi
  ACTION="push"
  NEW_COMMITS=$(git rev-list --count "$REMOTE_SHA..$LOCAL_SHA")
fi

TITLE="${TITLE:-$(git log -1 --format=%s)}"
TITLE="${TITLE#Draft: }"

echo "Branch:      $BRANCH → $BASE"
if [[ "$ACTION" == "push" ]]; then
  echo "Action:      push ($NEW_COMMITS commits new to the remote)"
else
  echo "Action:      recreate (remote branch equals local: delete it and push again)"
fi
echo "Title:       $TITLE"
echo "Assignee:    nobody ($USERNAME is unassigned)"
echo "On merge:    delete branch, squash"
echo "Description: ${DESCRIPTION_FILE:-GitLab default (the commit body)}"

if [[ "$PLAN" == 1 ]]; then
  exit 0
fi
if [[ "$ACTION" == "recreate" && "$RECREATE" != 1 ]]; then
  echo "Error: the branch is fully pushed; creating the MR needs --recreate-remote-branch." >&2
  exit 2
fi

# A push-created MR is always assigned to the pusher; with unassign GitLab recomputes
# assignees from an empty set. No "Draft:" prefix: a bot reviewer skips drafts.
OPTS=(
  -o merge_request.create
  -o "merge_request.target=$BASE"
  -o "merge_request.title=$TITLE"
  -o "merge_request.unassign=$USERNAME"
  -o merge_request.remove_source_branch
  -o merge_request.squash
)
if [[ -n "$DESCRIPTION_FILE" ]]; then
  DESCRIPTION=$(python3 -c 'import sys; print(open(sys.argv[1]).read().strip().replace("\n", "\\n"), end="")' "$DESCRIPTION_FILE")
  OPTS+=(-o "merge_request.description=$DESCRIPTION")
fi

if [[ "$ACTION" == "recreate" ]]; then
  git push origin --delete "$BRANCH"
fi
git push -u origin "$BRANCH" "${OPTS[@]}"

if ! print_mrs "$(open_mrs)"; then
  echo "Error: no MR appeared; read the remote: lines of the git push output." >&2
  exit 1
fi
