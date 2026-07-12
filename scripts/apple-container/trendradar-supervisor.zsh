#!/bin/zsh
set -u
umask 077

CONTAINER="${CONTAINER_BIN:-/usr/local/bin/container}"
CURL="${CURL_BIN:-/usr/bin/curl}"
JQ="${JQ_BIN:-/usr/bin/jq}"
NAME="${TREND_RADAR_CONTAINER_NAME:-trendradar}"
IMAGE="${TREND_RADAR_IMAGE:-ptilopsis-radar:latest}"
REPO="${REPO:-$HOME/PtilopsisRadar}"
LOG_DIR="${TREND_RADAR_LOG_DIR:-$HOME/Library/Logs/PtilopsisRadar}"
PYTHON="${PYTHON_BIN:-$REPO/.venv/bin/python}"
ALERT_PYTHON="${ALERT_PYTHON_BIN:-$PYTHON}"
ENV_FILE="${TREND_RADAR_ENV_FILE:-$REPO/docker/.env}"
HEALTH_URL="${TREND_RADAR_HEALTH_URL:-http://127.0.0.1:8080/}"
HEARTBEAT_FILE="${TREND_RADAR_HEARTBEAT_FILE:-$REPO/output/meta/last_task_completed.json}"
CURRENT_ARTIFACT="${TREND_RADAR_CURRENT_ARTIFACT:-$REPO/output/public/current/index.html}"
DAILY_ARTIFACT="${TREND_RADAR_DAILY_ARTIFACT:-$REPO/output/public/daily/full.html}"
CHECK_INTERVAL="${TREND_RADAR_CHECK_INTERVAL:-60}"
MAX_TASK_AGE="${TREND_RADAR_MAX_TASK_AGE:-5400}"
MAX_ARTIFACT_AGE="${TREND_RADAR_MAX_ARTIFACT_AGE:-10800}"
STARTUP_GRACE="${TREND_RADAR_STARTUP_GRACE:-3600}"
ALERT_REPEAT="${TREND_RADAR_ALERT_REPEAT:-3600}"
MEMORY="${TREND_RADAR_MEMORY:-1g}"
CPUS="${TREND_RADAR_CPUS:-2}"
LOG_MAX_BYTES="${TREND_RADAR_LOG_MAX_BYTES:-5242880}"
LOG_KEEP="${TREND_RADAR_LOG_KEEP:-5}"
CONTAINER_LOG_LINES="${TREND_RADAR_CONTAINER_LOG_LINES:-500}"
SUPERVISOR_LOG="$LOG_DIR/trendradar-supervisor.log"
CONTAINER_LOG="$LOG_DIR/trendradar-container.log"
ALERT_STATE="$REPO/output/meta/supervisor-alert.state"

mkdir -p "$LOG_DIR" "$REPO/output/meta"

rotate_log_if_needed() {
  local path="$1"
  [[ -f "$path" ]] || return 0
  local size
  size="$(/usr/bin/stat -f '%z' "$path" 2>/dev/null || print 0)"
  (( size >= LOG_MAX_BYTES )) || return 0
  rotate_generation "$path"
}

rotate_generation() {
  local path="$1"
  local index=$((LOG_KEEP - 1))
  while (( index >= 1 )); do
    [[ -f "$path.$index" ]] && /bin/mv -f "$path.$index" "$path.$((index + 1))"
    index=$((index - 1))
  done
  [[ -f "$path" ]] && /bin/mv -f "$path" "$path.1"
}

log() {
  rotate_log_if_needed "$SUPERVISOR_LOG"
  print -r -- "$(date -Iseconds) $*" >> "$SUPERVISOR_LOG"
}

iso_epoch() {
  "$PYTHON" -c \
    'from datetime import datetime; import sys; print(int(datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00")).timestamp()))' \
    "$1" 2>/dev/null
}

file_age() {
  local modified
  modified="$(/usr/bin/stat -f '%m' "$1" 2>/dev/null)" || return 1
  print $(( $(date +%s) - modified ))
}

send_operator_alert() {
  local code="$1"
  local detail="$2"
  local now prior_code prior_time
  now="$(date +%s)"
  prior_code=""
  prior_time=0
  if [[ -s "$ALERT_STATE" ]]; then
    IFS=$'\t' read -r prior_code prior_time < "$ALERT_STATE"
  fi
  if [[ "$prior_code" == "$code" ]] && (( now - prior_time < ALERT_REPEAT )); then
    log "alert suppressed code=$code repeat_window=${ALERT_REPEAT}s"
    return 0
  fi

  local message
  message="Ptilopsis Radar supervisor alert
Code: $code
Container: $NAME
Detail: $detail
Action: inspect supervisor diagnostics and recreate when drift is reported"
  if "$ALERT_PYTHON" -m trendradar.deployment.operator_alert \
      --env-file "$ENV_FILE" --message "$message" >> "$SUPERVISOR_LOG" 2>&1; then
    print -r -- "$code\t$now" > "$ALERT_STATE"
    log "operator alert delivered code=$code"
  else
    log "WARN operator alert delivery failed code=$code"
  fi
}

diagnostic_failure() {
  local return_code="$1"
  local code="$2"
  local detail="$3"
  log "ERROR code=$code detail=$detail"
  send_operator_alert "$code" "$detail"
  return "$return_code"
}

capture_container_logs() {
  local temporary="$CONTAINER_LOG.tmp"
  if "$CONTAINER" logs -n "$CONTAINER_LOG_LINES" "$NAME" > "$temporary" 2>/dev/null; then
    rotate_generation "$CONTAINER_LOG"
    /bin/mv -f "$temporary" "$CONTAINER_LOG"
  fi
}

create_container() {
  log "container missing; creating name=$NAME image=$IMAGE (local image only)"
  if ! "$CONTAINER" run -d \
      --name "$NAME" \
      --cpus "$CPUS" \
      --memory "$MEMORY" \
      --env-file "$ENV_FILE" \
      --env TZ=Asia/Shanghai \
      --mount source="$REPO/config",target=/app/config,readonly \
      --volume "$REPO/output:/app/output" \
      -p 127.0.0.1:8080:8080 \
      "$IMAGE" >> "$SUPERVISOR_LOG" 2>&1; then
    diagnostic_failure 70 "container_create_failed" \
      "local image exists but container creation failed"
    return $?
  fi
  log "container created; health checks resume on next cycle"
  return 0
}

run_check() {
  log "health check started name=$NAME image=$IMAGE"
  if ! "$CONTAINER" system start >/dev/null 2>&1; then
    diagnostic_failure 69 "container_system_unavailable" \
      "Apple Container system could not start"
    return $?
  fi

  local image_json target_digest
  image_json="$("$CONTAINER" image inspect "$IMAGE" 2>/dev/null)" || {
    diagnostic_failure 69 "local_image_missing" \
      "required local image $IMAGE is absent; build it locally before create"
    return $?
  }
  target_digest="$(print -r -- "$image_json" | "$JQ" -r \
    'if type == "array" then .[0] else . end | .configuration.descriptor.digest // .id // empty')"
  [[ -n "$target_digest" ]] || {
    diagnostic_failure 65 "local_image_identity_missing" \
      "local image inspect did not expose a digest"
    return $?
  }

  local inspect_json
  inspect_json="$("$CONTAINER" inspect "$NAME" 2>/dev/null)" || {
    create_container
    return $?
  }

  local state
  state="$(print -r -- "$inspect_json" | "$JQ" -r \
    'if type == "array" then .[0] else . end | .status.state // empty')"
  if [[ "$state" != "running" ]]; then
    log "container state=$state; starting"
    if ! "$CONTAINER" start "$NAME" >> "$SUPERVISOR_LOG" 2>&1; then
      diagnostic_failure 70 "container_start_failed" \
        "container exists but start failed"
      return $?
    fi
    log "container started; health checks resume on next cycle"
    return 0
  fi

  capture_container_logs

  local running_digest
  running_digest="$(print -r -- "$inspect_json" | "$JQ" -r \
    'if type == "array" then .[0] else . end | .configuration.image.descriptor.digest // empty')"
  if [[ -z "$running_digest" || "$running_digest" != "$target_digest" ]]; then
    diagnostic_failure 78 "image_drift" \
      "running container digest differs from local $IMAGE; recreate is required"
    return $?
  fi

  local created_iso created_epoch env_epoch
  created_iso="$(print -r -- "$inspect_json" | "$JQ" -r \
    'if type == "array" then .[0] else . end | .configuration.creationDate // .status.startedDate // empty')"
  created_epoch="$(iso_epoch "$created_iso")" || created_epoch=0
  if (( created_epoch <= 0 )); then
    diagnostic_failure 65 "container_identity_missing" \
      "container inspect did not expose a valid creation/start time"
    return $?
  fi
  env_epoch="$(/usr/bin/stat -f '%m' "$ENV_FILE" 2>/dev/null)" || env_epoch=0
  if (( env_epoch > created_epoch )); then
    diagnostic_failure 78 "env_drift" \
      "docker/.env is newer than the running container; recreate is required"
    return $?
  fi

  if ! "$CURL" --fail --silent --show-error --max-time 10 \
      "$HEALTH_URL" >/dev/null 2>&1; then
    diagnostic_failure 69 "http_unhealthy" \
      "configured HTTP endpoint is not reachable"
    return $?
  fi

  local now uptime heartbeat_age
  now="$(date +%s)"
  uptime=$(( now - created_epoch ))
  heartbeat_age="$(file_age "$HEARTBEAT_FILE")" || heartbeat_age=-1
  if (( heartbeat_age < 0 )); then
    if (( uptime > STARTUP_GRACE )); then
      diagnostic_failure 75 "task_heartbeat_missing" \
        "no completed scheduled-task heartbeat after startup grace"
      return $?
    fi
  elif (( heartbeat_age > MAX_TASK_AGE )); then
    diagnostic_failure 75 "task_heartbeat_stale" \
      "last completed scheduled task is older than ${MAX_TASK_AGE}s"
    return $?
  fi

  local current_age daily_age artifact_age
  current_age="$(file_age "$CURRENT_ARTIFACT")" || current_age=-1
  daily_age="$(file_age "$DAILY_ARTIFACT")" || daily_age=-1
  artifact_age="$current_age"
  if (( artifact_age < 0 || (daily_age >= 0 && daily_age < artifact_age) )); then
    artifact_age="$daily_age"
  fi
  if (( artifact_age < 0 )); then
    if (( uptime > STARTUP_GRACE )); then
      diagnostic_failure 75 "artifact_missing" \
        "neither current nor daily public artifact exists after startup grace"
      return $?
    fi
  elif (( artifact_age > MAX_ARTIFACT_AGE )); then
    diagnostic_failure 75 "artifact_stale" \
      "newest current/daily artifact is older than ${MAX_ARTIFACT_AGE}s"
    return $?
  fi

  if [[ -s "$ALERT_STATE" ]]; then
    : > "$ALERT_STATE"
    log "health recovered; prior alert state cleared"
  fi
  log "health check passed http=ok task_age=${heartbeat_age}s artifact_age=${artifact_age}s"
  return 0
}

cd "$REPO" || {
  log "ERROR code=repo_unavailable detail=cannot enter repository"
  exit 66
}

if [[ "${1:-}" == "--once" ]]; then
  run_check
  exit $?
fi

log "supervisor started interval=${CHECK_INTERVAL}s memory=$MEMORY cpus=$CPUS"
while true; do
  run_check || true
  sleep "$CHECK_INTERVAL"
done
