#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
WANT="${WORKERS:-3}"
mkdir -p "$DIR/logs"
RUNNING=$(pgrep -f "$DIR/worker.py" | wc -l | tr -d ' ')
for ((i = RUNNING; i < WANT; i++)); do
  nohup python3 "$DIR/worker.py" >> "$DIR/logs/worker.log" 2>&1 &
done
echo "workers running: $(pgrep -f "$DIR/worker.py" | wc -l | tr -d ' ') / $WANT"
