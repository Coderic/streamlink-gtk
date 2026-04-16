#!/usr/bin/env bash
# Download Python wheels for offline Flatpak pip install (no PyPI during flatpak-builder).
#
# Must match the CPython in org.gnome.Sdk (Flatpak), not necessarily the host `python3`.
# Default 3.13 matches org.gnome.Platform/Sdk 50 in typical installs; override if needed:
#   PIP_DOWNLOAD_PYTHON_VERSION=3.12 ./tools/fetch-pypi-wheels.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${ROOT}/flatpak/pypi-wheels"
REQ="${ROOT}/requirements.txt"
PYVER="${PIP_DOWNLOAD_PYTHON_VERSION:-3.13}"
SDK="${FLATPAK_SDK:-org.gnome.Sdk//50}"

mkdir -p "${DEST}"
rm -f "${DEST}"/*.whl 2>/dev/null || true

if [[ ! -f "${REQ}" ]]; then
  echo "Missing ${REQ}" >&2
  exit 1
fi

download_flatpak_sdk() {
  command -v flatpak >/dev/null 2>&1 || return 1
  flatpak info "$SDK" &>/dev/null || return 1
  echo "Downloading wheels using Flatpak SDK $SDK (same Python as flatpak-builder)…" >&2
  flatpak run \
    --share=network \
    --filesystem="${ROOT}:rw" \
    --command=python3 \
    "$SDK" -m pip download \
    --dest "${DEST}" \
    -r "${REQ}" \
    --only-binary=:all:
}

download_host() {
  echo "Downloading wheels for Python ${PYVER} (--python-version; override with PIP_DOWNLOAD_PYTHON_VERSION)…" >&2
  python3 -m pip download \
    --dest "${DEST}" \
    -r "${REQ}" \
    --python-version "${PYVER}" \
    --only-binary=:all:
}

if download_flatpak_sdk; then
  :
else
  echo "Note: install ${SDK} and re-run to match the Flatpak Python exactly, or rely on PIP_DOWNLOAD_PYTHON_VERSION." >&2
  download_host
fi

echo "Wheels: ${DEST} ($(find "${DEST}" -maxdepth 1 -name '*.whl' | wc -l) files)"
