#!/usr/bin/env bash
# Bundle a Meson DESTDIR (install prefix ${MINGW_PREFIX}, e.g. /ucrt64) into a portable zip
# for Windows: merge full Python stdlib from MSYS2, add FFmpeg, resolve MinGW DLLs into bin/.
#
# Prerequisite: DESTDIR=<this_root> meson install (so <this_root>/ucrt64/... exists when prefix is /ucrt64).
#
# Usage (MSYS2 UCRT64):
#   export MINGW_PREFIX=/ucrt64
#   DESTDIR="$PWD/staging" meson install -C build
#   ./tools/package-msys2-portable.sh "$PWD/staging" "$PWD/streamlink-gtk-VERSION-windows-x86_64.zip"
#
set -euo pipefail

DESTDIR_ROOT="${1:?DESTDIR root (directory that contains the ucrt64 folder)}"
ZIPOUT="${2:?output .zip path}"
MINGW_PREFIX="${MINGW_PREFIX:-/ucrt64}"

DESTDIR_ROOT="${DESTDIR_ROOT%/}"
MP_REL="${MINGW_PREFIX#/}"
SP="${DESTDIR_ROOT}/${MP_REL}"
if [[ ! -d "$SP" ]]; then
  echo "Expected directory not found: ${SP} (set MINGW_PREFIX=${MINGW_PREFIX})" >&2
  exit 1
fi

BIN="${SP}/bin"
LIB="${SP}/lib"
mkdir -p "${BIN}" "${LIB}"

PY_MAJOR="$("${MINGW_PREFIX}/bin/python3" -c 'import sys; print(sys.version_info.major)')"
PY_MINOR="$("${MINGW_PREFIX}/bin/python3" -c 'import sys; print(sys.version_info.minor)')")
PY_VER="${PY_MAJOR}.${PY_MINOR}"

# Python launcher + core DLLs from MinGW (DESTDIR usually does not include the interpreter)
for f in python3.exe python.exe pythonw.exe; do
  [[ -f "${MINGW_PREFIX}/bin/${f}" ]] && cp -f "${MINGW_PREFIX}/bin/${f}" "${BIN}/"
done
shopt -s nullglob
for f in "${MINGW_PREFIX}/bin"/libpython*.dll "${MINGW_PREFIX}/bin"/libffi*.dll \
         "${MINGW_PREFIX}/bin"/vcruntime*.dll; do
  [[ -f "$f" ]] && cp -f "$f" "${BIN}/"
done
shopt -u nullglob

# Full stdlib from MSYS2, merged with pip/meson content already under LIB/pythonX.Y
if [[ -d "${MINGW_PREFIX}/lib/python${PY_VER}" ]]; then
  mkdir -p "${LIB}"
  rsync -a "${MINGW_PREFIX}/lib/python${PY_VER}/" "${LIB}/python${PY_VER}/"
fi

if [[ -f "${MINGW_PREFIX}/bin/ffmpeg.exe" ]]; then
  cp -f "${MINGW_PREFIX}/bin/ffmpeg.exe" "${BIN}/"
fi

# Copy PE dependencies from the MinGW tree into bin/ (iterative closure)
added=1
for _round in $(seq 1 25); do
  added=0
  while IFS= read -r -d '' pe; do
    [[ "$pe" =~ \.(exe|dll)$ ]] || continue
    while IFS= read -r dll; do
      [[ -z "$dll" ]] && continue
      [[ "$dll" == *"${MINGW_PREFIX}"* ]] || [[ "$dll" == */ucrt64/* ]] || continue
      [[ -f "$dll" ]] || continue
      base="$(basename "$dll")"
      if [[ ! -f "${BIN}/${base}" ]]; then
        cp -f "$dll" "${BIN}/"
        added=1
      fi
    done < <(ldd "$pe" 2>/dev/null | awk '$2 == "=>" && $3 ~ /^\// {print $3}' || true)
  done < <(find "${BIN}" -maxdepth 1 \( -name '*.exe' -o -name '*.dll' \) -print0 2>/dev/null || true)
  [[ "$added" -eq 0 ]] && break
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[[ -f "${ROOT}/COPYING" ]] && cp -f "${ROOT}/COPYING" "${DESTDIR_ROOT}/"

VER="${GITHUB_REF_NAME:-0.0.1}"
cat > "${DESTDIR_ROOT}/README-WINDOWS.txt" << EOF
StreamlinkGTK ${VER} (MSYS2 UCRT64 bundle)

Use an "MSYS2 UCRT64" terminal. Add the extracted tree's ${MP_REL}/bin directory to PATH
(adjust the path to where you unpacked this zip), then run:

  streamlink-gtk

FFmpeg is included as ffmpeg.exe next to the Python binaries for Streamlink recording.

Licensing: see COPYING; MinGW/MYS2 runtime components follow upstream licenses.
EOF

ZIPABS="$(cd "$(dirname "$ZIPOUT")" && pwd)/$(basename "$ZIPOUT")"
(
  cd "${DESTDIR_ROOT}"
  zip -r -q "${ZIPABS}" .
)
echo "Created ${ZIPABS}"
