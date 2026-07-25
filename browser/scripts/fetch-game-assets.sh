#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RESOURCES_DIR="${PROJECT_ROOT}/resources"
RESOURCES_COMMIT="d8c73a9978633979ddf2ef8813f0152037a0d978"

if [[ ! -d "${RESOURCES_DIR}/.git" ]]; then
  git init "${RESOURCES_DIR}"
  git -C "${RESOURCES_DIR}" remote add origin \
    "https://github.com/open-toontown/resources.git"
  git -C "${RESOURCES_DIR}" fetch --depth=1 origin "${RESOURCES_COMMIT}"
  git -C "${RESOURCES_DIR}" checkout --detach FETCH_HEAD
fi

actual_commit="$(git -C "${RESOURCES_DIR}" rev-parse HEAD)"
if [[ "${actual_commit}" != "${RESOURCES_COMMIT}" ]]; then
  printf 'Unexpected resources checkout (wanted %s, got %s).\n' \
    "${RESOURCES_COMMIT}" "${actual_commit}" >&2
  exit 1
fi

printf 'Open Toontown resources: %s\n' "${RESOURCES_DIR}"
