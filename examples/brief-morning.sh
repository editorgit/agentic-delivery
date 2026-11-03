#!/bin/zsh
# Morning brief: keeps one tmux session with Claude in the repository and, each run,
# clears its context and sends /delivery:brief. Run it from launchd or cron on weekday
# mornings; read the brief with `tmux attach -t '=brief'` or in the Claude app.
#   brief-morning.sh <repo> [session-name]
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"
REPO=${1:?usage: brief-morning.sh <repo> [session-name]}
S=${2:-brief}
CMD="/delivery:brief"
log() { print -r -- "$(date '+%F %T') $*"; }

if ! tmux has-session -t "=$S" 2>/dev/null; then
  tmux new-session -d -s "$S" -c "$REPO"
  tmux send-keys -t "=$S:" "claude -n $S '$CMD'" C-m
  log "new session $S"
  exit 0
fi

# The pane runs claude (its process name is a version number) or a bare shell if claude exited.
case "$(tmux display-message -p -t "=$S:" '#{pane_current_command}')" in
  zsh|bash|sh|fish)
    tmux send-keys -t "=$S:" "claude -n $S '$CMD'" C-m
    log "claude restarted in $S"
    ;;
  *)
    # A new day starts with an empty context: yesterday's conversation does not pile up.
    tmux send-keys -t "=$S:" Escape
    sleep 1
    tmux send-keys -t "=$S:" "/clear" C-m
    sleep 3
    tmux send-keys -t "=$S:" "$CMD" C-m
    log "/clear + $CMD in $S"
    ;;
esac
