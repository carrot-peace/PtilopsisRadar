#!/bin/zsh
set -u

CONTAINER="/usr/local/bin/container"
NAME="trendradar"
IMAGE="ptilopsis-radar:latest"
REPO="$HOME/PtilopsisRadar"
LOG_DIR="$HOME/Library/Logs/PtilopsisRadar"
CHECK_INTERVAL="${TREND_RADAR_CHECK_INTERVAL:-60}"
MEMORY="${TREND_RADAR_MEMORY:-1g}"
CPUS="${TREND_RADAR_CPUS:-2}"

mkdir -p "$LOG_DIR"
mkdir -p "$REPO/output"

exec >> "$LOG_DIR/trendradar-supervisor.log" 2>&1

echo "==== $(date -Iseconds) supervisor started ===="
echo "repo=$REPO"
echo "image=$IMAGE"
echo "memory=$MEMORY"
echo "cpus=$CPUS"
echo "interval=$CHECK_INTERVAL"

cd "$REPO" || {
  echo "ERROR: cannot cd to repo: $REPO"
  exit 66
}

while true; do
  echo "---- $(date -Iseconds) health check ----"

  "$CONTAINER" system start || {
    echo "WARN: container system start failed"
    sleep "$CHECK_INTERVAL"
    continue
  }

  if ! "$CONTAINER" inspect "$NAME" >/dev/null 2>&1; then
    echo "container $NAME missing; creating with image $IMAGE"

    "$CONTAINER" run -d \
      --name "$NAME" \
      --cpus "$CPUS" \
      --memory "$MEMORY" \
      --env-file "$REPO/docker/.env" \
      --env TZ=Asia/Shanghai \
      --mount source="$REPO/config",target=/app/config,readonly \
      --volume "$REPO/output:/app/output" \
      -p 127.0.0.1:8080:8080 \
      "$IMAGE"

    sleep "$CHECK_INTERVAL"
    continue
  fi

  if "$CONTAINER" inspect "$NAME" | /usr/bin/grep -q '"state"[[:space:]]*:[[:space:]]*"running"'; then
    echo "container $NAME is running"
  else
    echo "container $NAME exists but is not running; starting"
    "$CONTAINER" start "$NAME" || echo "WARN: failed to start $NAME"
  fi

  sleep "$CHECK_INTERVAL"
done
