#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EMSDK_DIR="$PROJECT_DIR/.toolchain/emsdk"
ENGINE_DIR="$PROJECT_DIR/.toolchain/build/panda3d-emscripten"
PYTHON_ROOT="$PROJECT_DIR/.toolchain/python-wasm-root/usr/local"
WORK_DIR="$PROJECT_DIR/.build-wasm/browser"
DIST_DIR="$PROJECT_DIR/dist-web"
DIRECT_PACKAGE_DIR="$WORK_DIR/engine-direct"
BROWSER_CLIENT_PACKAGE_DIR="$WORK_DIR/browser-client"
GAME_OTP_PACKAGE_DIR="$WORK_DIR/game-otp"
GAME_TOONTOWN_PACKAGE_DIR="$WORK_DIR/game-toontown"
GAME_ETC_PACKAGE_DIR="$WORK_DIR/game-etc"
COLD_PHASE_35_PACKAGE_DIR="$WORK_DIR/cold-phase-3.5"
KEYBIND_PATCH="$PROJECT_DIR/browser/patches/panda3d-direct-keybinds.patch"
SPRINT_PATCH="$PROJECT_DIR/browser/patches/panda3d-direct-sprint.patch"
GAME_BUILD=0
RELEASE_BUILD=0
PYTHON_BYTECODE=1
LOCAL_ASTRON_DEVELOPMENT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --game)
      GAME_BUILD=1
      ;;
    --release)
      RELEASE_BUILD=1
      ;;
    --python-source-only)
      PYTHON_BYTECODE=0
      ;;
    --local-astron-development)
      LOCAL_ASTRON_DEVELOPMENT=1
      ;;
    *)
      echo "Usage: $0 [--game] [--release] [--python-source-only] [--local-astron-development]" >&2
      exit 2
      ;;
  esac
  shift
done

if [[ $RELEASE_BUILD -eq 1 && $LOCAL_ASTRON_DEVELOPMENT -eq 1 ]]; then
  echo "Release builds cannot enable direct local Astron development." >&2
  exit 2
fi
if [[ $LOCAL_ASTRON_DEVELOPMENT -eq 1 ]]; then
  BROWSER_PROFILE="enabled"
else
  BROWSER_PROFILE="disabled"
fi

for required in \
  "$EMSDK_DIR/emsdk_env.sh" \
  "$ENGINE_DIR/lib/libpy.panda3d.core.cpython-312-wasm32-emscripten.a" \
  "$ENGINE_DIR/lib/libpy.panda3d.ode.cpython-312-wasm32-emscripten.a" \
  "$ENGINE_DIR/lib/libpy.panda3d.physics.cpython-312-wasm32-emscripten.a" \
  "$ENGINE_DIR/lib/libpy.panda3d.otp.cpython-312-wasm32-emscripten.a" \
  "$ENGINE_DIR/lib/libpy.panda3d.toontown.cpython-312-wasm32-emscripten.a" \
  "$ENGINE_DIR/lib/libp3openal_audio.a" \
  "$ENGINE_DIR/lib/libpandaode.a" \
  "$PROJECT_DIR/.toolchain/src/panda3d-open-toontown/thirdparty/emscripten-libs/ode/lib/libode.a" \
  "$PYTHON_ROOT/lib/libpython3.12.a"; do
  if [[ ! -f "$required" ]]; then
    echo "Missing build input: $required" >&2
    echo "Run browser/scripts/bootstrap-toolchain.sh and browser/scripts/build-engine.sh first." >&2
    exit 1
  fi
done

# shellcheck disable=SC1091
source "$EMSDK_DIR/emsdk_env.sh" >/dev/null

rm -rf "$WORK_DIR" "$DIST_DIR"
mkdir -p "$WORK_DIR/python-home/lib" "$DIST_DIR"

# Package Direct from a disposable copy so the browser control override is
# reproducible even when an existing local toolchain predates the patch.
rsync -a \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  "$ENGINE_DIR/direct/" "$DIRECT_PACKAGE_DIR/"
if grep -q "keybindVariables" "$DIRECT_PACKAGE_DIR/controls/ControlManager.py"; then
  : # A freshly rebuilt toolchain already contains the keybind support.
elif patch --batch --dry-run -p3 -d "$DIRECT_PACKAGE_DIR" < "$KEYBIND_PATCH" >/dev/null; then
  patch -p3 -d "$DIRECT_PACKAGE_DIR" < "$KEYBIND_PATCH" >/dev/null
else
  echo "Could not apply the browser keybind patch to Panda3D Direct." >&2
  exit 1
fi
if grep -q "avatar-sprint-multiplier" "$DIRECT_PACKAGE_DIR/controls/GravityWalker.py"; then
  : # A freshly rebuilt toolchain already contains sprint support.
elif patch --batch --dry-run -p3 -d "$DIRECT_PACKAGE_DIR" < "$SPRINT_PATCH" >/dev/null; then
  patch -p3 -d "$DIRECT_PACKAGE_DIR" < "$SPRINT_PATCH" >/dev/null
else
  echo "Could not apply the browser sprint patch to Panda3D Direct." >&2
  exit 1
fi
python3 "$PROJECT_DIR/browser/scripts/configure-browser-profile.py" \
  --direct-dir "$DIRECT_PACKAGE_DIR" \
  --local-astron-development "$BROWSER_PROFILE"

rsync -a \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  "$PROJECT_DIR/browser/client/" "$BROWSER_CLIENT_PACKAGE_DIR/"
python3 "$PROJECT_DIR/browser/scripts/configure-browser-profile.py" \
  --client-dir "$BROWSER_CLIENT_PACKAGE_DIR" \
  --local-astron-development "$BROWSER_PROFILE"

LAUNCHER_DEFINES=("-DOPEN_TOONTOWN_BROWSER_BUILD=1")
PRELOAD_ARGS=(
  --preload-file "$WORK_DIR/python-home@/python"
  --preload-file "$ENGINE_DIR/panda3d@/engine/panda3d"
  --preload-file "$DIRECT_PACKAGE_DIR@/engine/direct"
  --preload-file "$BROWSER_CLIENT_PACKAGE_DIR@/app"
)

if [[ $GAME_BUILD -eq 1 ]]; then
  for required in "$PROJECT_DIR/resources/phase_3" \
                  "$PROJECT_DIR/resources/phase_3.5" \
                  "$PROJECT_DIR/resources/phase_4" "$PROJECT_DIR/otp" \
                  "$PROJECT_DIR/toontown" "$PROJECT_DIR/etc"; do
    if [[ ! -d "$required" ]]; then
      echo "Full game build input is missing: $required" >&2
      echo "Clone https://github.com/open-toontown/resources into resources/ first." >&2
      exit 1
    fi
  done
  LAUNCHER_DEFINES+=("-DOPEN_TOONTOWN_GAME_BUILD=1")
  rsync -a \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    "$PROJECT_DIR/otp/" "$GAME_OTP_PACKAGE_DIR/"
  rsync -a \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    "$PROJECT_DIR/toontown/" "$GAME_TOONTOWN_PACKAGE_DIR/"
  python3 "$PROJECT_DIR/browser/scripts/prune-browser-python.py" \
    "$GAME_OTP_PACKAGE_DIR" \
    "$GAME_TOONTOWN_PACKAGE_DIR"
  python3 "$PROJECT_DIR/browser/scripts/generate-battle-sound-index.py" \
    --resources-root "$PROJECT_DIR/resources" \
    --output "$BROWSER_CLIENT_PACKAGE_DIR/_browser_battle_sound_index.py"
  rsync -a "$PROJECT_DIR/etc/" "$GAME_ETC_PACKAGE_DIR/"
  python3 "$PROJECT_DIR/browser/scripts/prune-browser-dc.py" \
    "$GAME_ETC_PACKAGE_DIR"
  # Phase 3.5 contains the early Toon/tutorial resources that avoid cold actor
  # construction stalls.  Its optional news models are nearly 60 MiB by
  # themselves, so keep those in an independently cached background package.
  rsync -a \
    --exclude='models/news/' \
    "$PROJECT_DIR/resources/phase_3.5/" "$COLD_PHASE_35_PACKAGE_DIR/"
  PRELOAD_ARGS+=(
    --preload-file "$GAME_OTP_PACKAGE_DIR@/game/otp"
    --preload-file "$GAME_TOONTOWN_PACKAGE_DIR@/game/toontown"
    --preload-file "$GAME_ETC_PACKAGE_DIR@/etc"
    --preload-file "$PROJECT_DIR/resources/models@/resources/models"
    --preload-file "$PROJECT_DIR/resources/phase_3@/resources/phase_3"
    --preload-file "$COLD_PHASE_35_PACKAGE_DIR@/resources/phase_3.5"
  )
fi

# A browser does not need CPython's test suites, desktop UI modules, package
# installer, native extension directory, or build metadata. Keeping the rest
# of the standard library makes the legacy client migration less brittle.
rsync -a \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='config-*/' \
  --exclude='ensurepip/' \
  --exclude='idlelib/' \
  --exclude='lib-dynload/' \
  --exclude='site-packages/' \
  --exclude='test/' \
  --exclude='tkinter/' \
  --exclude='turtledemo/' \
  "$PYTHON_ROOT/lib/python3.12" "$WORK_DIR/python-home/lib/"

if [[ $GAME_BUILD -eq 1 ]]; then
  python3 -m pip install \
    --disable-pip-version-check \
    --no-deps \
    --no-compile \
    --quiet \
    --target "$WORK_DIR/python-home/lib/python3.12/site-packages" \
    -r "$PROJECT_DIR/browser/requirements-wasm.txt"
fi

if [[ $PYTHON_BYTECODE -eq 1 ]]; then
  PYTHON312_BIN="${PYTHON312_BIN:-python3.12}"
  if ! command -v "$PYTHON312_BIN" >/dev/null; then
    echo "Python 3.12 is required to generate browser bytecode." >&2
    exit 1
  fi
  if [[ "$("$PYTHON312_BIN" -c 'import sys; print("%s.%s" % sys.version_info[:2])')" != "3.12" ]]; then
    echo "PYTHON312_BIN must point to CPython 3.12." >&2
    exit 1
  fi
  BYTECODE_DIRS=("$BROWSER_CLIENT_PACKAGE_DIR")
  if [[ $GAME_BUILD -eq 1 ]]; then
    BYTECODE_DIRS+=("$GAME_OTP_PACKAGE_DIR" "$GAME_TOONTOWN_PACKAGE_DIR")
  fi
  "$PYTHON312_BIN" -m compileall \
    --invalidation-mode unchecked-hash \
    -q -f "${BYTECODE_DIRS[@]}"
fi

rsync -a "$PROJECT_DIR/browser/web/" "$DIST_DIR/"
python3 "$PROJECT_DIR/browser/scripts/configure-browser-profile.py" \
  --web-dir "$DIST_DIR" \
  --local-astron-development "$BROWSER_PROFILE"

if [[ $RELEASE_BUILD -eq 1 ]]; then
  EMSCRIPTEN_PROFILE_ARGS=(-s ASSERTIONS=0)
else
  EMSCRIPTEN_PROFILE_ARGS=(-s ASSERTIONS=2 --minify 0)
fi

em++ \
  -x c++ \
  -std=gnu++14 \
  -O2 \
  "${LAUNCHER_DEFINES[@]}" \
  -DLINK_ALL_STATIC= \
  -I"$PYTHON_ROOT/include/python3.12" \
  -I"$ENGINE_DIR/include" \
  -c "$PROJECT_DIR/browser/launcher/main.c" \
  -o "$WORK_DIR/main.o"

MODULE_LIBS=(
  "$ENGINE_DIR/lib/libpy.panda3d.core.cpython-312-wasm32-emscripten.a"
  "$ENGINE_DIR/lib/libpy.panda3d.direct.cpython-312-wasm32-emscripten.a"
  "$ENGINE_DIR/lib/libpy.panda3d.ode.cpython-312-wasm32-emscripten.a"
  "$ENGINE_DIR/lib/libpy.panda3d.physics.cpython-312-wasm32-emscripten.a"
  "$ENGINE_DIR/lib/libpy.panda3d.otp.cpython-312-wasm32-emscripten.a"
  "$ENGINE_DIR/lib/libpy.panda3d.toontown.cpython-312-wasm32-emscripten.a"
)

ENGINE_LIBS=(
  "$ENGINE_DIR/lib/libp3openal_audio.a"
  "$ENGINE_DIR/lib/libp3toontown.a"
  "$ENGINE_DIR/lib/libp3otp.a"
  "$ENGINE_DIR/lib/libp3direct.a"
  "$ENGINE_DIR/lib/libpandaode.a"
  "$ENGINE_DIR/lib/libpandaphysics.a"
  "$ENGINE_DIR/lib/libp3webgldisplay.a"
  "$ENGINE_DIR/lib/libpanda.a"
  "$ENGINE_DIR/lib/libpandaexpress.a"
  "$ENGINE_DIR/lib/libp3dtool.a"
  "$ENGINE_DIR/lib/libp3dtoolconfig.a"
  "$PROJECT_DIR/.toolchain/src/panda3d-open-toontown/thirdparty/emscripten-libs/ode/lib/libode.a"
)

em++ \
  -O2 \
  -o "$DIST_DIR/open-toontown.js" \
  "$WORK_DIR/main.o" \
  -Wl,--start-group \
  "${MODULE_LIBS[@]}" \
  -Wl,--whole-archive \
  "${ENGINE_LIBS[@]}" \
  -Wl,--no-whole-archive \
  "$PYTHON_ROOT/lib/libpython3.12.a" \
  "$PYTHON_ROOT/lib/libmpdec.a" \
  "$PYTHON_ROOT/lib/libexpat.a" \
  "$PYTHON_ROOT/lib/libHacl_Hash_SHA2.a" \
  -Wl,--end-group \
  -lmimalloc \
  -lopenal \
  -lwebsocket.js \
  -s USE_VORBIS=1 \
  -s USE_ZLIB=1 \
  -s USE_BZIP2=1 \
  -s USE_SQLITE3=1 \
  -s USE_FREETYPE=1 \
  -s USE_HARFBUZZ=1 \
  -s USE_LIBPNG=1 \
  -s GL_ENABLE_GET_PROC_ADDRESS=1 \
  -s MAX_WEBGL_VERSION=2 \
  -s ALLOW_MEMORY_GROWTH=1 \
  -s INITIAL_MEMORY=134217728 \
  -s STACK_SIZE=2097152 \
  "${EMSCRIPTEN_PROFILE_ARGS[@]}" \
  -s EXIT_RUNTIME=0 \
  -s EXPORTED_RUNTIME_METHODS=FS \
  "${PRELOAD_ARGS[@]}"

if [[ $GAME_BUILD -eq 1 ]]; then
  python3 "$PROJECT_DIR/browser/scripts/prune-browser-python.py" \
    --verify-only \
    --verify-index "$DIST_DIR/open-toontown.js" \
    "$GAME_OTP_PACKAGE_DIR" \
    "$GAME_TOONTOWN_PACKAGE_DIR"
fi

if [[ $GAME_BUILD -eq 1 ]]; then
  python3 "$PROJECT_DIR/browser/scripts/build-phase-packages.py" \
    "$PROJECT_DIR" \
    "$DIST_DIR" \
    "$EMSDK_DIR/upstream/emscripten/tools/file_packager.py"
  python3 "$PROJECT_DIR/browser/scripts/build-short-audio-banks.py" \
    --project-root "$PROJECT_DIR" \
    --config "$PROJECT_DIR/browser/audio-banks.json" \
    --output-dir "$DIST_DIR" \
    --manifest "$DIST_DIR/audio-bank-manifest.json"
fi

RUNTIME_VERSION="$({
  shasum -a 256 "$DIST_DIR/open-toontown.js"
  shasum -a 256 "$DIST_DIR/open-toontown.wasm"
  shasum -a 256 "$DIST_DIR/open-toontown.data"
  if [[ -f "$DIST_DIR/phase-manifest.json" ]]; then
    shasum -a 256 "$DIST_DIR/phase-manifest.json"
  fi
  if [[ -f "$DIST_DIR/audio-bank-manifest.json" ]]; then
    shasum -a 256 "$DIST_DIR/audio-bank-manifest.json"
  fi
  while IFS= read -r audio_bank_asset; do
    shasum -a 256 "$audio_bank_asset"
  done < <(
    find "$DIST_DIR" -maxdepth 1 -type f \
      -name 'audio-bank-*.data' | sort
  )
  if [[ -f "$DIST_DIR/short-audio-banks.js" ]]; then
    shasum -a 256 "$DIST_DIR/short-audio-banks.js"
  fi
  if [[ -f "$DIST_DIR/runtime-authority.js" ]]; then
    shasum -a 256 "$DIST_DIR/runtime-authority.js"
  fi
  if [[ -f "$DIST_DIR/secure-asset-cache.js" ]]; then
    shasum -a 256 "$DIST_DIR/secure-asset-cache.js"
  fi
} | shasum -a 256 | awk '{print $1}')"
perl -pi -e \
  "s/__TOONTOWN_RUNTIME_VERSION__/$RUNTIME_VERSION/g" \
  "$DIST_DIR/app.js"

if [[ $RELEASE_BUILD -eq 1 ]]; then
  python3 "$PROJECT_DIR/browser/scripts/verify-production-client.py" \
    "$DIST_DIR"
fi

while IFS= read -r -d '' asset; do
  gzip -1 -n -c "$asset" > "$asset.gz"
done < <(find "$DIST_DIR" -type f \( \
  -name '*.css' -o \
  -name '*.data' -o \
  -name '*.js' -o \
  -name '*.json' -o \
  -name '*.wasm' \
\) -print0)

echo "Browser build: $DIST_DIR"
if [[ $GAME_BUILD -eq 1 ]]; then
  echo "Mode: phase-streamed Open Toontown client"
else
  echo "Mode: WebAssembly engine proof"
fi
if [[ $RELEASE_BUILD -eq 1 ]]; then
  echo "Profile: release"
else
  echo "Profile: debug"
fi
if [[ $LOCAL_ASTRON_DEVELOPMENT -eq 1 ]]; then
  echo "Local Astron development: enabled"
else
  echo "Local Astron development: disabled"
fi
if [[ $PYTHON_BYTECODE -eq 1 ]]; then
  echo "Python packaging: sanitized CPython 3.12 bytecode"
else
  echo "Python packaging: sanitized source only"
fi
du -sh "$DIST_DIR"
