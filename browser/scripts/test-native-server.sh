#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SERVER_ENGINE="${PROJECT_ROOT}/.toolchain/build/panda3d-native-server"
PYTHON_BIN="${HOST_PYTHON:-$(command -v python3.12 || true)}"

if [[ -z "${PYTHON_BIN}" ]]; then
  printf 'Python 3.12 is required.\n' >&2
  exit 1
fi
if ! command -v brew >/dev/null 2>&1; then
  printf 'Homebrew ODE is required.\n' >&2
  exit 1
fi

ODE_PREFIX="$(brew --prefix ode)"
export PYTHONPATH="${SERVER_ENGINE}:${PROJECT_ROOT}"
export DYLD_LIBRARY_PATH="${SERVER_ENGINE}/lib:${ODE_PREFIX}/lib"

exec "${PYTHON_BIN}" "${PROJECT_ROOT}/browser/tests/smoke_native_server.py"
