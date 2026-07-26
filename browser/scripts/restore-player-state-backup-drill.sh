#!/usr/bin/env bash
set -euo pipefail

umask 077

readonly repository="luisncg/toontown-player-state-backups"
readonly identity="${TOONTOWN_BACKUP_AGE_IDENTITY:-/Users/luiscg/.ssh/toontown-player-state-backup-age.key}"

if [[ ! -r "${identity}" ]]; then
  echo "The off-host backup decryption identity is unavailable." >&2
  exit 1
fi

temporary_root="$(mktemp -d)"
cleanup() {
  rm -rf -- "${temporary_root}"
}
trap cleanup EXIT INT TERM

gh repo clone "${repository}" "${temporary_root}/repository" -- \
  --quiet \
  --depth 1
manifest="${temporary_root}/repository/latest.json"
if [[ ! -s "${manifest}" ]]; then
  echo "The latest backup manifest is unavailable." >&2
  exit 1
fi

readarray_value() {
  python3 -c \
    'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' \
    "${manifest}" "$1"
}

archive_relative="$(readarray_value archive)"
expected_digest="$(readarray_value plaintextSha256)"
encrypted_archive="${temporary_root}/repository/${archive_relative}"
plain_archive="${temporary_root}/player-state.tar.gz"

case "${archive_relative}" in
  snapshots/toontown-player-state-*.tar.gz.age) ;;
  *)
    echo "The backup manifest references an unexpected archive." >&2
    exit 1
    ;;
esac

age --decrypt \
  --identity "${identity}" \
  --output "${plain_archive}" \
  "${encrypted_archive}"
actual_digest="$(shasum -a 256 "${plain_archive}" | awk '{print $1}')"
if [[ "${actual_digest}" != "${expected_digest}" ]]; then
  echo "The decrypted backup digest does not match its manifest." >&2
  exit 1
fi

tar -tzf "${plain_archive}" >"${temporary_root}/entries.txt"
if grep -Eq '(^/|(^|/)\.\.(/|$))' "${temporary_root}/entries.txt"; then
  echo "The backup archive contains an unsafe path." >&2
  exit 1
fi
if ! grep -q '^astron/databases/' "${temporary_root}/entries.txt"; then
  echo "The backup does not contain the Astron database." >&2
  exit 1
fi
if ! grep -q '^data/' "${temporary_root}/entries.txt"; then
  echo "The backup does not contain application player state." >&2
  exit 1
fi

mkdir "${temporary_root}/restored"
tar -xzf "${plain_archive}" --directory "${temporary_root}/restored"
test -d "${temporary_root}/restored/astron/databases"
test -d "${temporary_root}/restored/data"
test -n "$(find "${temporary_root}/restored/astron/databases" -type f -print -quit)"

echo "Non-destructive player-state restore drill passed."
