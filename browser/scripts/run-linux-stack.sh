#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SERVER_ENGINE="${PROJECT_ROOT}/.toolchain/build/panda3d-native-server"
ASTRON_DIR="${PROJECT_ROOT}/astron/linux"
ASTRON_BINARY="${ASTRON_DIR}/astrond"
ASTRON_CONFIG="${ASTRON_CONFIG:-../config/astrond.yml}"
LOG_DIR="${TOONTOWN_LOG_DIR:-${PROJECT_ROOT}/.build-wasm/logs}"
PYTHON_BIN="${HOST_PYTHON:-$(command -v python3.12 || true)}"
PIDS=()
AI_CONFIG_FILES=("etc/Configrc.prc")

if [[ "${FISH_BINGO_FORCE_ACTIVE:-0}" == "1" ]]; then
  AI_CONFIG_FILES+=("browser/config/fish-bingo-smoke.prc")
fi

if [[ "$(uname -s)" != "Linux" ]]; then
  printf 'This runner is intended for the Linux server.\n' >&2
  exit 1
fi
if [[ -z "${PYTHON_BIN}" ]]; then
  printf 'Python 3.12 is required.\n' >&2
  exit 1
fi
if [[ ! -x "${ASTRON_BINARY}" ]]; then
  printf 'Astron is missing: %s\n' "${ASTRON_BINARY}" >&2
  exit 1
fi
if ! find "${SERVER_ENGINE}/panda3d" -maxdepth 1 \
    -name 'toontown.cpython-312-*.so' -print -quit | grep -q .; then
  printf 'The native Linux server engine is missing. Run npm run build:server first.\n' >&2
  exit 1
fi
if [[ ! -f "${PROJECT_ROOT}/dist-web/open-toontown.wasm" ]] &&
   ! {
     [[ "${TOONTOWN_PRODUCTION:-0}" == "1" ]] &&
     [[ -n "${R2_ASSET_MANIFEST_PATH:-}" ]] &&
     [[ -s "${R2_ASSET_MANIFEST_PATH}" ]]
   }; then
  printf 'The browser game is missing. Run npm run build:game on the build Mac first.\n' >&2
  exit 1
fi
if [[ ! -d "${PROJECT_ROOT}/node_modules/ws" ]]; then
  printf 'Node dependencies are missing. Run npm ci --omit=dev first.\n' >&2
  exit 1
fi

for port in 7197 7198 7199 7200 8180; do
  if ss -H -ltn "sport = :${port}" | grep -q .; then
    printf 'Port %s is already in use; refusing to stop an unknown process.\n' "${port}" >&2
    exit 1
  fi
done

mkdir -p "${LOG_DIR}" "${PROJECT_ROOT}/astron/logs" "${PROJECT_ROOT}/data"

cleanup() {
  local pid
  trap - EXIT INT TERM
  for pid in "${PIDS[@]}"; do
    if kill -0 "${pid}" >/dev/null 2>&1; then
      kill "${pid}" >/dev/null 2>&1 || true
    fi
  done
  wait "${PIDS[@]}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait_for_port() {
  local port="$1"
  local label="$2"
  local attempts="${3:-120}"
  local attempt
  for ((attempt = 1; attempt <= attempts; attempt += 1)); do
    if ss -H -ltn "sport = :${port}" | grep -q .; then
      return 0
    fi
    sleep 0.25
  done
  printf '%s did not listen on port %s. See %s.\n' \
    "${label}" "${port}" "${LOG_DIR}" >&2
  return 1
}

wait_for_log() {
  local file="$1"
  local pattern="$2"
  local label="$3"
  local attempts="${4:-480}"
  local attempt
  for ((attempt = 1; attempt <= attempts; attempt += 1)); do
    if grep -Eq "${pattern}" "${file}" 2>/dev/null; then
      return 0
    fi
    sleep 0.25
  done
  printf '%s did not become ready. See %s.\n' \
    "${label}" "${file}" >&2
  return 1
}

export PYTHONPATH="${SERVER_ENGINE}:${PROJECT_ROOT}"
export LD_LIBRARY_PATH="${SERVER_ENGINE}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
export PYTHONDONTWRITEBYTECODE=1

(
  cd "${ASTRON_DIR}"
  exec ./astrond --loglevel info "${ASTRON_CONFIG}"
) >"${LOG_DIR}/astron.log" 2>&1 &
PIDS+=("$!")
wait_for_port 7199 "Astron message director"
wait_for_port 7198 "Astron client agent"

(
  cd "${PROJECT_ROOT}"
  exec "${PYTHON_BIN}" -u -m toontown.uberdog.UDStart \
    --base-channel 1000000 \
    --max-channels 999999 \
    --stateserver 4002 \
    --messagedirector-ip 127.0.0.1:7199 \
    --eventlogger-ip 127.0.0.1:7197
) >"${LOG_DIR}/uberdog.log" 2>&1 &
PIDS+=("$!")
wait_for_log "${LOG_DIR}/uberdog.log" 'UberDOG server is ready\.' "UberDOG"

(
  cd "${PROJECT_ROOT}"
  exec "${PYTHON_BIN}" -u -m toontown.ai.AIStart \
    --base-channel 401000000 \
    --max-channels 999999 \
    --stateserver 4002 \
    --messagedirector-ip 127.0.0.1:7199 \
    --eventlogger-ip 127.0.0.1:7197 \
    --district-name 'Toon Valley' \
    "${AI_CONFIG_FILES[@]}"
) >"${LOG_DIR}/ai.log" 2>&1 &
PIDS+=("$!")
wait_for_log "${LOG_DIR}/ai.log" 'ToontownAIRepository: Done\.' "AI district"

node "${PROJECT_ROOT}/browser/gateway/server.mjs" \
  >"${LOG_DIR}/gateway.log" 2>&1 &
PIDS+=("$!")
wait_for_port 7200 "WebSocket gateway"

node "${PROJECT_ROOT}/browser/scripts/serve.mjs" "${PROJECT_ROOT}/dist-web" \
  >"${LOG_DIR}/web.log" 2>&1 &
PIDS+=("$!")
wait_for_port 8180 "browser server"

printf 'Toontown Browser is ready on loopback at http://127.0.0.1:8180\n'
printf 'Logs: %s\n' "${LOG_DIR}"

while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "${pid}" >/dev/null 2>&1; then
      printf 'A stack process exited. See %s.\n' "${LOG_DIR}" >&2
      exit 1
    fi
  done
  sleep 2
done
