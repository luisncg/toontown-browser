#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENGINE_DIR="${PROJECT_ROOT}/.toolchain/src/panda3d-open-toontown"
OUTPUT_DIR="${PROJECT_ROOT}/.toolchain/build/panda3d-native-server"
PANDA3D_COMMIT="06615744481946654610833679a0893589114504"
PANDA3D_REPOSITORY="https://github.com/open-toontown/panda3d.git"
HOST_PYTHON="${HOST_PYTHON:-$(command -v python3.12 || true)}"
BUILD_JOBS="${BUILD_JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || getconf _NPROCESSORS_ONLN)}"
HOST_SYSTEM="$(uname -s)"
HOST_ARCH="$(uname -m)"

if [[ -z "${HOST_PYTHON}" ]]; then
  printf 'Python 3.12 is required to build and run the Open Toontown server.\n' >&2
  exit 1
fi

mkdir -p "${PROJECT_ROOT}/.toolchain/src" "${PROJECT_ROOT}/.toolchain/build"
if [[ ! -d "${ENGINE_DIR}/.git" ]]; then
  git init "${ENGINE_DIR}"
  git -C "${ENGINE_DIR}" remote add origin "${PANDA3D_REPOSITORY}"
  git -C "${ENGINE_DIR}" fetch --depth=1 origin "${PANDA3D_COMMIT}"
  git -C "${ENGINE_DIR}" checkout --detach FETCH_HEAD
fi

ENGINE_COMMIT="$(git -C "${ENGINE_DIR}" rev-parse HEAD)"
if [[ "${ENGINE_COMMIT}" != "${PANDA3D_COMMIT}" ]]; then
  printf 'Unexpected Panda3D checkout (wanted %s, got %s).\n' \
    "${PANDA3D_COMMIT}" "${ENGINE_COMMIT}" >&2
  exit 1
fi

case "${HOST_SYSTEM}" in
  Darwin)
    if ! command -v brew >/dev/null 2>&1; then
      printf 'Homebrew and its ode package are required for the native macOS server build.\n' >&2
      exit 1
    fi
    ODE_PREFIX="$(brew --prefix ode 2>/dev/null || true)"
    ODE_INCLUDE_DIR="${ODE_PREFIX}/include"
    ODE_LIBRARY_DIR="${ODE_PREFIX}/lib"
    TARGET="darwin"
    TARGET_ARCH="${HOST_ARCH}"
    if [[ ! -f "${ODE_LIBRARY_DIR}/libode.dylib" ]]; then
      printf 'Homebrew ODE is missing. Install it with: brew install ode\n' >&2
      exit 1
    fi
    if [[ -d /opt/homebrew/opt/bison/bin ]]; then
      PATH="/opt/homebrew/opt/bison/bin:${PATH}"
    fi
    if [[ -d /opt/homebrew/opt/flex/bin ]]; then
      PATH="/opt/homebrew/opt/flex/bin:${PATH}"
    fi
    ;;
  Linux)
    if [[ "${HOST_ARCH}" != "x86_64" && "${HOST_ARCH}" != "aarch64" ]]; then
      printf 'Unsupported Linux architecture: %s\n' "${HOST_ARCH}" >&2
      exit 1
    fi
    if ! command -v pkg-config >/dev/null 2>&1 || ! pkg-config --exists ode; then
      printf 'The Linux ODE development package is missing (Ubuntu: libode-dev).\n' >&2
      exit 1
    fi
    ODE_INCLUDE_DIR="$(pkg-config --variable=includedir ode)"
    ODE_LIBRARY_DIR="$(pkg-config --variable=libdir ode)"
    TARGET="linux"
    TARGET_ARCH="${HOST_ARCH/aarch64/arm64}"
    ;;
  *)
    printf 'Unsupported host operating system: %s\n' "${HOST_SYSTEM}" >&2
    exit 1
    ;;
esac
export PATH

(
  cd "${ENGINE_DIR}"
  "${HOST_PYTHON}" makepanda/makepanda.py \
    --git-commit="${ENGINE_COMMIT}" \
    --target "${TARGET}" \
    --arch "${TARGET_ARCH}" \
    --outputdir="${OUTPUT_DIR}" \
    --nothing \
    --use-python \
    --use-direct \
    --use-pandaphysics \
    --use-pandaparticlesystem \
    --use-ode \
    --ode-incdir="${ODE_INCLUDE_DIR}" \
    --ode-libdir="${ODE_LIBRARY_DIR}" \
    --use-zlib \
    --use-png \
    --use-egg \
    --use-freetype \
    --use-harfbuzz \
    --use-openssl \
    --use-nametag \
    --use-movement \
    --use-dna \
    --use-suit \
    --use-pets \
    --no-pandatool \
    --no-deploytools \
    --optimize 3 \
    --threads "${BUILD_JOBS}"
)

printf 'Native Panda3D server runtime: %s\n' "${OUTPUT_DIR}"
