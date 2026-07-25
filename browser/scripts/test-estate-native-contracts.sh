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

export PYTHONPATH="${SERVER_ENGINE}:${PROJECT_ROOT}"
exec "${PYTHON_BIN}" "${PROJECT_ROOT}/browser/tests/test_estate_native_contracts.py"
