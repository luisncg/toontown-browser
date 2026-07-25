#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TOOLCHAIN_DIR="${PROJECT_ROOT}/.toolchain"
EMSDK_DIR="${TOOLCHAIN_DIR}/emsdk"
CPYTHON_DIR="${TOOLCHAIN_DIR}/src/cpython-3.12.8"
CPYTHON_ARCHIVE="${TOOLCHAIN_DIR}/downloads/Python-3.12.8.tar.xz"
PYTHON_WASM_ROOT="${TOOLCHAIN_DIR}/python-wasm-root"
PANDA3D_DIR="${TOOLCHAIN_DIR}/src/panda3d-open-toontown"
ODE_DIR="${TOOLCHAIN_DIR}/src/ode"

EMSDK_VERSION="4.0.2"
CPYTHON_VERSION="3.12.8"
PANDA3D_COMMIT="06615744481946654610833679a0893589114504"
ODE_COMMIT="bcfb66cd5e18e32e27cfaae3651ead930bbcda13"
BUILD_JOBS="${BUILD_JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || getconf _NPROCESSORS_ONLN)}"

mkdir -p "${TOOLCHAIN_DIR}/downloads" "${TOOLCHAIN_DIR}/src"

clone_pinned_repo() {
  local url="$1"
  local commit="$2"
  local destination="$3"

  if [[ ! -d "${destination}/.git" ]]; then
    git init "${destination}"
    git -C "${destination}" remote add origin "${url}"
    git -C "${destination}" fetch --depth=1 origin "${commit}"
    git -C "${destination}" checkout --detach FETCH_HEAD
  fi

  local actual_commit
  actual_commit="$(git -C "${destination}" rev-parse HEAD)"
  if [[ "${actual_commit}" != "${commit}" ]]; then
    printf 'Unexpected checkout at %s (wanted %s, got %s).\n' \
      "${destination}" "${commit}" "${actual_commit}" >&2
    exit 1
  fi
}

clone_pinned_repo \
  "https://github.com/open-toontown/panda3d.git" \
  "${PANDA3D_COMMIT}" \
  "${PANDA3D_DIR}"
clone_pinned_repo \
  "https://github.com/thomasmarsh/ODE.git" \
  "${ODE_COMMIT}" \
  "${ODE_DIR}"

if [[ ! -d "${EMSDK_DIR}/.git" ]]; then
  git clone --filter=blob:none https://github.com/emscripten-core/emsdk.git "${EMSDK_DIR}"
fi

"${EMSDK_DIR}/emsdk" install "${EMSDK_VERSION}"
"${EMSDK_DIR}/emsdk" activate "${EMSDK_VERSION}"

# emsdk_env.sh defines the pinned compiler, Node, and cache paths.
set +u
source "${EMSDK_DIR}/emsdk_env.sh"
set -u

if [[ ! -f "${PYTHON_WASM_ROOT}/usr/local/lib/libpython3.12.a" ]]; then
  if [[ ! -f "${CPYTHON_ARCHIVE}" ]]; then
    curl --fail --location --output "${CPYTHON_ARCHIVE}" \
      "https://www.python.org/ftp/python/${CPYTHON_VERSION}/Python-${CPYTHON_VERSION}.tar.xz"
  fi

  if [[ ! -d "${CPYTHON_DIR}" ]]; then
    tar -xJf "${CPYTHON_ARCHIVE}" -C "${TOOLCHAIN_DIR}/src"
    mv "${TOOLCHAIN_DIR}/src/Python-${CPYTHON_VERSION}" "${CPYTHON_DIR}"
  fi

  (
    cd "${CPYTHON_DIR}"
    EM_CONFIG="${EMSDK_DIR}/.emscripten" \
      python3 Tools/wasm/wasm_build.py emscripten-browser
  )

  make -C "${CPYTHON_DIR}/builddir/emscripten-browser" \
    -j"${BUILD_JOBS}" install DESTDIR="${PYTHON_WASM_ROOT}"

  cp "${CPYTHON_DIR}/builddir/emscripten-browser/Modules/_hacl/libHacl_Hash_SHA2.a" \
    "${PYTHON_WASM_ROOT}/usr/local/lib/"
  cp "${CPYTHON_DIR}/builddir/emscripten-browser/Modules/_decimal/libmpdec/libmpdec.a" \
    "${PYTHON_WASM_ROOT}/usr/local/lib/"
  cp "${CPYTHON_DIR}/builddir/emscripten-browser/Modules/expat/libexpat.a" \
    "${PYTHON_WASM_ROOT}/usr/local/lib/"
fi

"${EMSDK_DIR}/upstream/emscripten/emcc" --version | head -n 1
"${PYTHON_WASM_ROOT}/usr/local/bin/python3.12" --version 2>/dev/null || true
printf 'Python WebAssembly SDK: %s\n' "${PYTHON_WASM_ROOT}/usr/local"
