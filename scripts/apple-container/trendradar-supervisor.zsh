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
MAX_CURRENT_ARTIFACT_AGE="${TREND_RADAR_MAX_CURRENT_ARTIFACT_AGE:-${TREND_RADAR_MAX_ARTIFACT_AGE:-10800}}"
MAX_DAILY_ARTIFACT_AGE="${TREND_RADAR_MAX_DAILY_ARTIFACT_AGE:-108000}"
STARTUP_GRACE="${TREND_RADAR_STARTUP_GRACE:-3600}"
DAILY_STARTUP_GRACE="${TREND_RADAR_DAILY_STARTUP_GRACE:-108000}"
READINESS_TIMEOUT="${TREND_RADAR_READINESS_TIMEOUT:-30}"
READINESS_INTERVAL="${TREND_RADAR_READINESS_INTERVAL:-2}"
COMMAND_TIMEOUT="${TREND_RADAR_COMMAND_TIMEOUT:-30}"
ALERT_REPEAT="${TREND_RADAR_ALERT_REPEAT:-3600}"
MEMORY="${TREND_RADAR_MEMORY:-1g}"
CPUS="${TREND_RADAR_CPUS:-2}"
LOG_MAX_BYTES="${TREND_RADAR_LOG_MAX_BYTES:-5242880}"
LOG_KEEP="${TREND_RADAR_LOG_KEEP:-5}"
CONTAINER_LOG_LINES="${TREND_RADAR_CONTAINER_LOG_LINES:-500}"
SUPERVISOR_LOG="$LOG_DIR/trendradar-supervisor.log"
CONTAINER_LOG="$LOG_DIR/trendradar-container.log"
ALERT_STATE="$REPO/output/meta/supervisor-alerts.json"
DEPLOYMENT_STATE="$REPO/output/meta/supervisor-deployment-state.json"

mkdir -p "$LOG_DIR" "$REPO/output/meta"

rotate_log_if_needed() {
  local path="$1"
  [[ -f "$path" ]] || return 0
  # Logging is used while reporting invalid configuration, so rotation must
  # not evaluate unchecked values as arithmetic first.
  is_positive_integer "$LOG_MAX_BYTES" || return 0
  is_positive_integer "$LOG_KEEP" || return 0
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
  local modified age
  modified="$(/usr/bin/stat -f '%m' "$1" 2>/dev/null)" || return 1
  age=$(( $(date +%s) - modified ))
  (( age < 0 )) && age=0
  print "$age"
}

is_positive_integer() {
  [[ "$1" == <-> ]] && (( $1 > 0 ))
}

run_with_timeout() {
  local timeout_seconds="$1"
  shift
  "$PYTHON" -c '
import os
import signal
import subprocess
import sys

process = subprocess.Popen(sys.argv[2:], start_new_session=True)
try:
    return_code = process.wait(timeout=float(sys.argv[1]))
except subprocess.TimeoutExpired:
    os.killpg(process.pid, signal.SIGKILL)
    process.wait()
    raise SystemExit(124)
raise SystemExit(return_code)
' "$timeout_seconds" "$@"
}

monotonic_seconds() {
  "$PYTHON" -c 'import time; print(int(time.monotonic()))'
}

send_operator_alert() {
  local code="$1"
  local detail="$2"
  local repeat="$ALERT_REPEAT"
  is_positive_integer "$repeat" || repeat=3600
  local message
  message="Ptilopsis Radar supervisor alert
Code: $code
Container: $NAME
Detail: $detail
Action: inspect supervisor diagnostics and recreate when drift is reported"
  if "$ALERT_PYTHON" -m trendradar.deployment.operator_alert \
      --env-file "$ENV_FILE" \
      --message "$message" \
      --code "$code" \
      --state-path "$ALERT_STATE" \
      --repeat-seconds "$repeat" >> "$SUPERVISOR_LOG" 2>&1; then
    log "operator alert handled code=$code"
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

validate_configuration() {
  local entry name value
  for entry in \
      "CHECK_INTERVAL:$CHECK_INTERVAL" \
      "MAX_TASK_AGE:$MAX_TASK_AGE" \
      "MAX_CURRENT_ARTIFACT_AGE:$MAX_CURRENT_ARTIFACT_AGE" \
      "MAX_DAILY_ARTIFACT_AGE:$MAX_DAILY_ARTIFACT_AGE" \
      "STARTUP_GRACE:$STARTUP_GRACE" \
      "DAILY_STARTUP_GRACE:$DAILY_STARTUP_GRACE" \
      "READINESS_TIMEOUT:$READINESS_TIMEOUT" \
      "READINESS_INTERVAL:$READINESS_INTERVAL" \
      "COMMAND_TIMEOUT:$COMMAND_TIMEOUT" \
      "ALERT_REPEAT:$ALERT_REPEAT" \
      "LOG_MAX_BYTES:$LOG_MAX_BYTES" \
      "LOG_KEEP:$LOG_KEEP" \
      "CONTAINER_LOG_LINES:$CONTAINER_LOG_LINES"; do
    name="${entry%%:*}"
    value="${entry#*:}"
    if ! is_positive_integer "$value"; then
      diagnostic_failure 64 "supervisor_config_invalid" \
        "$name must be a positive integer"
      return $?
    fi
  done
  return 0
}

capture_container_logs() {
  local temporary="$CONTAINER_LOG.tmp"
  if run_with_timeout "$COMMAND_TIMEOUT" \
      "$CONTAINER" logs -n "$CONTAINER_LOG_LINES" "$NAME" \
      > "$temporary" 2>/dev/null; then
    rotate_generation "$CONTAINER_LOG"
    /bin/mv -f "$temporary" "$CONTAINER_LOG"
  fi
}

create_container() {
  log "container missing; creating name=$NAME image=$IMAGE (local image only)"
  if ! run_with_timeout "$COMMAND_TIMEOUT" "$CONTAINER" run -d \
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
  return 0
}

inspect_json=""
wait_until_ready() {
  local deadline now remaining attempt_timeout sleep_seconds state
  deadline=$(( $(monotonic_seconds) + READINESS_TIMEOUT ))
  while true; do
    now="$(monotonic_seconds)" || return 1
    remaining=$(( deadline - now ))
    (( remaining > 0 )) || break
    attempt_timeout="$COMMAND_TIMEOUT"
    (( attempt_timeout > remaining )) && attempt_timeout="$remaining"
    inspect_json="$(run_with_timeout "$attempt_timeout" \
      "$CONTAINER" inspect "$NAME" 2>/dev/null)" || inspect_json=""
    if [[ -n "$inspect_json" ]]; then
      state="$(print -r -- "$inspect_json" | "$JQ" -r \
        'if type == "array" then .[0] else . end | .status.state // empty')"
      if [[ "$state" == "running" ]]; then
        now="$(monotonic_seconds)" || return 1
        remaining=$(( deadline - now ))
        (( remaining > 0 )) || break
        attempt_timeout=10
        (( attempt_timeout > remaining )) && attempt_timeout="$remaining"
        if run_with_timeout "$attempt_timeout" \
            "$CURL" --fail --silent --show-error --max-time "$attempt_timeout" \
              "$HEALTH_URL" >/dev/null 2>&1; then
          return 0
        fi
      fi
    fi
    now="$(monotonic_seconds)" || return 1
    remaining=$(( deadline - now ))
    (( remaining > 0 )) || break
    sleep_seconds="$READINESS_INTERVAL"
    (( sleep_seconds > remaining )) && sleep_seconds="$remaining"
    sleep "$sleep_seconds"
  done
  return 1
}

check_artifact() {
  local label="$1"
  local artifact_path="$2"
  local max_age="$3"
  local grace="$4"
  local uptime="$5"
  local age
  age="$(file_age "$artifact_path")" || age=-1
  log "$label artifact observed age=${age}s max_age=${max_age}s grace=${grace}s uptime=${uptime}s"
  if (( age < 0 )); then
    if (( uptime > grace )); then
      diagnostic_failure 75 "${label}_artifact_missing" \
        "$label artifact is missing after ${grace}s startup grace"
      return $?
    fi
    log "$label artifact missing within startup grace uptime=${uptime}s"
  elif (( age > max_age )); then
    if (( uptime > grace )); then
      diagnostic_failure 75 "${label}_artifact_stale" \
        "$label artifact age ${age}s exceeds ${max_age}s"
      return $?
    fi
    log "$label artifact stale within startup grace age=${age}s uptime=${uptime}s"
  fi
  print "$age"
  return 0
}

run_check() {
  log "health check started name=$NAME image=$IMAGE"
  if [[ ! -r "$ENV_FILE" ]]; then
    diagnostic_failure 78 "env_file_missing" \
      "configured environment file is missing or unreadable"
    return $?
  fi
  if ! run_with_timeout "$COMMAND_TIMEOUT" \
      "$CONTAINER" system start >/dev/null 2>&1; then
    diagnostic_failure 69 "container_system_unavailable" \
      "Apple Container system could not start"
    return $?
  fi

  local image_json target_digest
  image_json="$(run_with_timeout "$COMMAND_TIMEOUT" \
    "$CONTAINER" image inspect "$IMAGE" 2>/dev/null)" || {
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

  local state started_this_cycle=0
  inspect_json="$(run_with_timeout "$COMMAND_TIMEOUT" \
    "$CONTAINER" inspect "$NAME" 2>/dev/null)" || inspect_json=""
  if [[ -z "$inspect_json" ]]; then
    create_container || return $?
    started_this_cycle=1
  else
    state="$(print -r -- "$inspect_json" | "$JQ" -r \
      'if type == "array" then .[0] else . end | .status.state // empty')"
    if [[ "$state" != "running" ]]; then
      log "container state=$state; starting"
      if ! run_with_timeout "$COMMAND_TIMEOUT" \
          "$CONTAINER" start "$NAME" >> "$SUPERVISOR_LOG" 2>&1; then
        diagnostic_failure 70 "container_start_failed" \
          "container exists but start failed"
        return $?
      fi
      started_this_cycle=1
    fi
  fi

  if (( started_this_cycle )); then
    if ! wait_until_ready; then
      diagnostic_failure 69 "container_not_ready" \
        "container did not become running and HTTP-ready within ${READINESS_TIMEOUT}s"
      return $?
    fi
  elif ! "$CURL" --fail --silent --show-error --max-time 10 \
      "$HEALTH_URL" >/dev/null 2>&1; then
    diagnostic_failure 69 "http_unhealthy" \
      "configured HTTP endpoint is not reachable"
    return $?
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

  local created_iso started_iso created_epoch started_epoch now
  created_iso="$(print -r -- "$inspect_json" | "$JQ" -r \
    'if type == "array" then .[0] else . end | .configuration.creationDate // empty')"
  started_iso="$(print -r -- "$inspect_json" | "$JQ" -r \
    'if type == "array" then .[0] else . end | .status.startedDate // empty')"
  created_epoch="$(iso_epoch "$created_iso")" || created_epoch=0
  started_epoch="$(iso_epoch "$started_iso")" || started_epoch=0
  now="$(date +%s)"
  if (( created_epoch <= 0 || started_epoch <= 0 \
      || created_epoch > started_epoch \
      || created_epoch > now + 300 \
      || started_epoch > now + 300 )); then
    diagnostic_failure 65 "container_identity_missing" \
      "container inspect did not expose ordered, current creation and start times"
    return $?
  fi

  local env_status
  env_status="$("$PYTHON" -m trendradar.deployment.supervisor_state deployment \
    --state-path "$DEPLOYMENT_STATE" \
    --env-file "$ENV_FILE" \
    --container-created "$created_iso" \
    --image-digest "$running_digest" 2>/dev/null)" || env_status="invalid"
  case "$env_status" in
    ok|baseline_created) ;;
    missing)
      diagnostic_failure 78 "env_file_missing" \
        "configured environment file is missing or unreadable"
      return $?
      ;;
    drift)
      diagnostic_failure 78 "env_drift" \
        "environment content differs from the container baseline; recreate is required"
      return $?
      ;;
    *)
      diagnostic_failure 65 "env_state_invalid" \
        "supervisor deployment state is invalid or could not be written"
      return $?
      ;;
  esac

  local uptime heartbeat_json heartbeat_status heartbeat_age
  uptime=$(( now - started_epoch ))
  heartbeat_json="$("$PYTHON" -m trendradar.deployment.supervisor_state heartbeat \
    --path "$HEARTBEAT_FILE" \
    --now-epoch "$now" \
    --started-epoch "$started_epoch" \
    --max-age "$MAX_TASK_AGE" 2>/dev/null)" || heartbeat_json='{"status":"invalid","age_seconds":-1}'
  heartbeat_status="$(print -r -- "$heartbeat_json" | "$JQ" -r '.status // "invalid"')"
  heartbeat_age="$(print -r -- "$heartbeat_json" | "$JQ" -r '.age_seconds // -1')"
  case "$heartbeat_status" in
    fresh) ;;
    missing|before_start|stale)
      if (( uptime > STARTUP_GRACE )); then
        diagnostic_failure 75 "task_heartbeat_${heartbeat_status}" \
          "scheduled-task heartbeat status is $heartbeat_status after startup grace"
        return $?
      fi
      log "task heartbeat status=$heartbeat_status within startup grace uptime=${uptime}s"
      ;;
    future|invalid|*)
      diagnostic_failure 75 "task_heartbeat_${heartbeat_status}" \
        "scheduled-task heartbeat is not trustworthy"
      return $?
      ;;
  esac

  local current_age daily_age
  current_age="$(check_artifact current "$CURRENT_ARTIFACT" \
    "$MAX_CURRENT_ARTIFACT_AGE" "$STARTUP_GRACE" "$uptime")" || return $?
  daily_age="$(check_artifact daily "$DAILY_ARTIFACT" \
    "$MAX_DAILY_ARTIFACT_AGE" "$DAILY_STARTUP_GRACE" "$uptime")" || return $?

  if ! "$ALERT_PYTHON" -m trendradar.deployment.operator_alert \
      --state-path "$ALERT_STATE" --clear-state >> "$SUPERVISOR_LOG" 2>&1; then
    diagnostic_failure 74 "alert_state_clear_failed" \
      "active supervisor incident state could not be cleared"
    return $?
  fi
  log "health check passed http=ok task_age=${heartbeat_age}s current_age=${current_age}s daily_age=${daily_age}s"
  return 0
}

cd "$REPO" || {
  log "ERROR code=repo_unavailable detail=cannot enter repository"
  exit 66
}

validate_configuration
configuration_status=$?
(( configuration_status == 0 )) || exit "$configuration_status"

if [[ "${1:-}" == "--once" ]]; then
  run_check
  exit $?
fi

log "supervisor started interval=${CHECK_INTERVAL}s memory=$MEMORY cpus=$CPUS"
while true; do
  run_check || true
  sleep "$CHECK_INTERVAL"
done
