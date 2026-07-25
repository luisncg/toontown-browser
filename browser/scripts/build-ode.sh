#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TOOLCHAIN_DIR="${PROJECT_ROOT}/.toolchain"
EMSDK_DIR="${TOOLCHAIN_DIR}/emsdk"
ODE_DIR="${TOOLCHAIN_DIR}/src/ode"
BUILD_DIR="${TOOLCHAIN_DIR}/build/ode-emscripten"
PANDA3D_ODE_DIR="${TOOLCHAIN_DIR}/src/panda3d-open-toontown/thirdparty/emscripten-libs/ode"
ODE_PATCH="${PROJECT_ROOT}/browser/patches/ode-emscripten.patch"
BUILD_JOBS="${BUILD_JOBS:-$(sysctl -n hw.ncpu 2>/dev/null || getconf _NPROCESSORS_ONLN)}"

if [[ ! -f "${EMSDK_DIR}/emsdk_env.sh" ]] || [[ ! -d "${ODE_DIR}/.git" ]]; then
  "${SCRIPT_DIR}/bootstrap-toolchain.sh"
fi

if git -C "${ODE_DIR}" apply --reverse --check "${ODE_PATCH}" 2>/dev/null; then
  : # Patch is already present in the project-local ODE checkout.
elif git -C "${ODE_DIR}" apply --check "${ODE_PATCH}"; then
  git -C "${ODE_DIR}" apply "${ODE_PATCH}"
else
  printf 'Could not apply ODE patch: %s\n' "${ODE_PATCH}" >&2
  exit 1
fi

set +u
source "${EMSDK_DIR}/emsdk_env.sh"
set -u

emcmake cmake -S "${ODE_DIR}" -B "${BUILD_DIR}" \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DODE_DOUBLE_PRECISION=OFF \
  -DODE_NO_BUILTIN_THREADING_IMPL=ON \
  -DODE_NO_THREADING_INTF=ON \
  -DODE_WITH_DEMOS=OFF \
  -DODE_WITH_TESTS=OFF \
  -DODE_WITH_LIBCCD=OFF \
  -DODE_WITH_OPCODE=ON
cmake --build "${BUILD_DIR}" --parallel "${BUILD_JOBS}"

mkdir -p "${PANDA3D_ODE_DIR}/include" "${PANDA3D_ODE_DIR}/lib"
rsync -a "${ODE_DIR}/include/ode" "${PANDA3D_ODE_DIR}/include/"
rsync -a "${BUILD_DIR}/include/ode/" "${PANDA3D_ODE_DIR}/include/ode/"
cp "${BUILD_DIR}/libode.a" "${PANDA3D_ODE_DIR}/lib/libode.a"

printf 'ODE WebAssembly library: %s\n' "${PANDA3D_ODE_DIR}/lib/libode.a"
