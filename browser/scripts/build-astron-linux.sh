#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SOURCE_DIR="${PROJECT_ROOT}/.toolchain/src/astron"
BUILD_DIR="${PROJECT_ROOT}/.toolchain/build/astron-linux"
OUTPUT_DIR="${PROJECT_ROOT}/astron/linux"
ASTRON_COMMIT="3ad54903b6ec3d4fd796043f558732fbb326a59c"
ASTRON_REPOSITORY="https://github.com/Astron/Astron.git"
BUILD_JOBS="${BUILD_JOBS:-$(getconf _NPROCESSORS_ONLN)}"

if [[ "$(uname -s)" != "Linux" ]]; then
  printf 'This script builds the Linux Astron daemon and must run on Linux.\n' >&2
  exit 1
fi
for command in cmake git; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "${command}" >&2
    exit 1
  fi
done

mkdir -p "$(dirname "${SOURCE_DIR}")" "${BUILD_DIR}" "${OUTPUT_DIR}"
if [[ ! -d "${SOURCE_DIR}/.git" ]]; then
  git init "${SOURCE_DIR}"
  git -C "${SOURCE_DIR}" remote add origin "${ASTRON_REPOSITORY}"
  git -C "${SOURCE_DIR}" fetch --depth=1 origin "${ASTRON_COMMIT}"
  git -C "${SOURCE_DIR}" checkout --detach FETCH_HEAD
fi

ACTUAL_COMMIT="$(git -C "${SOURCE_DIR}" rev-parse HEAD)"
if [[ "${ACTUAL_COMMIT}" != "${ASTRON_COMMIT}" ]]; then
  printf 'Unexpected Astron checkout (wanted %s, got %s).\n' \
    "${ASTRON_COMMIT}" "${ACTUAL_COMMIT}" >&2
  exit 1
fi

cmake -S "${SOURCE_DIR}" -B "${BUILD_DIR}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CXX_FLAGS=-Wno-error=maybe-uninitialized \
  -DBUILD_TESTS=OFF \
  -DYAMLCPP_USE_STATIC_LIBS=OFF
cmake --build "${BUILD_DIR}" --parallel "${BUILD_JOBS}"
install -m 0755 "${BUILD_DIR}/astrond" "${OUTPUT_DIR}/astrond"

printf 'Linux Astron daemon: %s\n' "${OUTPUT_DIR}/astrond"
