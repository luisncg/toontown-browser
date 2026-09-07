#!/usr/bin/env bash
# Apply a reviewed Toontown release without making per-change backups.
set -euo pipefail
stage="${1:?staged release directory required}"
release="${2:?release hash required}"
[[ "$stage" =~ ^/home/luisadmin/toontown-classic-[A-Za-z0-9]+$ ]]
[[ "$release" =~ ^[a-f0-9]{64}$ ]]
app=/srv/toontown-browser/app
environment=/etc/toontown-browser/environment
private=/srv/toontown-browser/private/r2-assets.json

# Validate everything before touching the active release.
node - "$stage" "$release" <<'JS'
const fs = require('fs');
const [stage, release] = process.argv.slice(2);
const manifest = JSON.parse(fs.readFileSync(stage + '/r2-assets.json'));
const app = fs.readFileSync(stage + '/dist-web/app.js', 'utf8');
if (manifest.release !== release || !app.includes('const runtimeAssetVersion = "' + release + '";')) {
  throw new Error('Staged release identity mismatch');
}
JS
node --check "$stage/source/browser/shared/game-authority.mjs"
node --check "$stage/source/browser/server/world-composition.mjs"
python3 - "$stage/source" <<'PY'
from pathlib import Path
import sys
for path in Path(sys.argv[1]).rglob('*.py'):
    compile(path.read_bytes(), str(path), 'exec')
PY

# Only application sources and public artifacts are staged. Player data and
# scheduled daily player-state backups are outside this operation.
systemctl stop toontown-browser.service
rsync -a --chown=toontown-browser:toontown-browser "$stage/source/" "$app/"
rsync -a --chown=root:root "$stage/dist-web/" "$app/dist-web/"
install -o root -g toontown-browser -m 640 "$stage/r2-assets.json" "$private"
if grep -q '^R2_ASSET_RELEASE=' "$environment"; then
  sed -i "s|^R2_ASSET_RELEASE=.*|R2_ASSET_RELEASE=$release|" "$environment"
else
  printf 'R2_ASSET_RELEASE=%s\n' "$release" >> "$environment"
fi
systemctl start toontown-browser.service
for attempt in {1..30}; do
  if systemctl is-active --quiet toontown-browser.service &&
      curl -fsS http://127.0.0.1:8180/ >/dev/null; then
    printf 'Deployed release %s; no per-change backup created.\n' "$release"
    exit 0
  fi
  sleep 1
done
echo 'Service has not become ready; inspect the Toontown journal.' >&2
exit 1
