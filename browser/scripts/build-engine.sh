#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TOOLCHAIN_DIR="${PROJECT_ROOT}/.toolchain"
EMSDK_DIR="${TOOLCHAIN_DIR}/emsdk"
ENGINE_DIR="${TOOLCHAIN_DIR}/src/panda3d-open-toontown"
PYTHON_WASM_PREFIX="${TOOLCHAIN_DIR}/python-wasm-root/usr/local"
OUTPUT_DIR="${TOOLCHAIN_DIR}/build/panda3d-emscripten"
EMSCRIPTEN_PATCHES=(
  "${PROJECT_ROOT}/browser/patches/panda3d-emscripten-static-init.patch"
  "${PROJECT_ROOT}/browser/patches/panda3d-emscripten-distributed.patch"
  "${PROJECT_ROOT}/browser/patches/panda3d-emscripten-websocket.patch"
  "${PROJECT_ROOT}/browser/patches/panda3d-direct-keybinds.patch"
  "${PROJECT_ROOT}/browser/patches/panda3d-direct-sprint.patch"
  "${PROJECT_ROOT}/browser/patches/panda3d-emscripten-scaled-pointer.patch"
  "${PROJECT_ROOT}/browser/patches/panda3d-emscripten-focus-recovery.patch"
  "${PROJECT_ROOT}/browser/patches/panda3d-emscripten-binary-alpha.patch"
)
BUILD_JOBS="${BUILD_JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || getconf _NPROCESSORS_ONLN)}"
HOST_PYTHON="${HOST_PYTHON:-$(command -v python3.12 || true)}"

if [[ -z "${HOST_PYTHON}" ]]; then
  printf 'Python 3.12 is required on the host to match the target SDK.\n' >&2
  exit 1
fi

if [[ ! -f "${EMSDK_DIR}/emsdk_env.sh" ]] || \
   [[ ! -f "${PYTHON_WASM_PREFIX}/lib/libpython3.12.a" ]]; then
  "${SCRIPT_DIR}/bootstrap-toolchain.sh"
fi

set +u
source "${EMSDK_DIR}/emsdk_env.sh"
set -u

"${SCRIPT_DIR}/build-ode.sh"

if [[ -d /opt/homebrew/opt/bison/bin ]]; then
  PATH="/opt/homebrew/opt/bison/bin:${PATH}"
fi
if [[ -d /opt/homebrew/opt/flex/bin ]]; then
  PATH="/opt/homebrew/opt/flex/bin:${PATH}"
fi
export PATH

for emscripten_patch in "${EMSCRIPTEN_PATCHES[@]}"; do
  case "$(basename "${emscripten_patch}")" in
    panda3d-direct-keybinds.patch)
      if grep -q "keybindVariables" "${ENGINE_DIR}/direct/src/controls/ControlManager.py"; then
        continue
      fi
      ;;
    panda3d-direct-sprint.patch)
      if grep -q "avatar-sprint-multiplier" "${ENGINE_DIR}/direct/src/controls/GravityWalker.py"; then
        continue
      fi
      ;;
  esac

  if git -C "${ENGINE_DIR}" apply --reverse --check "${emscripten_patch}" 2>/dev/null; then
    : # Patch is already present in the project-local engine checkout.
  elif git -C "${ENGINE_DIR}" apply --check "${emscripten_patch}"; then
    git -C "${ENGINE_DIR}" apply "${emscripten_patch}"
  else
    printf 'Could not apply Panda3D patch: %s\n' "${emscripten_patch}" >&2
    exit 1
  fi
done

ENGINE_COMMIT="$(git -C "${ENGINE_DIR}" rev-parse HEAD)"
mkdir -p "${TOOLCHAIN_DIR}/build"

(
  cd "${ENGINE_DIR}"
  "${HOST_PYTHON}" makepanda/makepanda.py \
    --git-commit="${ENGINE_COMMIT}" \
    --target emscripten \
    --python-incdir="${PYTHON_WASM_PREFIX}/include" \
    --python-libdir="${PYTHON_WASM_PREFIX}/lib" \
    --outputdir="${OUTPUT_DIR}" \
    --static \
    --everything \
    --no-pandatool \
    --no-deploytools \
    --verbose \
    --threads="${BUILD_JOBS}"
)

printf 'Panda3D WebAssembly build: %s\n' "${OUTPUT_DIR}"
