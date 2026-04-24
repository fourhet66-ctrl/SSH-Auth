#!/usr/bin/env sh
set -eu

REPO_URL="${SSH_AUTH_REPO_URL:-https://github.com/fourhet66-ctrl/SSH-Auth}"
REF="${SSH_AUTH_REF:-main}"
DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
INSTALL_DIR="${SSH_AUTH_INSTALL_DIR:-${DATA_HOME}/ssh-auth/source}"
WORK_DIR="${INSTALL_DIR}.tmp.$$"
ARCHIVE="${WORK_DIR}/ssh-auth.tar.gz"

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT HUP INT TERM

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'error: required command not found: %s\n' "$1" >&2
    exit 1
  fi
}

download() {
  url=$1
  output=$2

  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$output"
    return
  fi

  if command -v wget >/dev/null 2>&1; then
    wget -qO "$output" "$url"
    return
  fi

  printf 'error: install requires curl or wget\n' >&2
  exit 1
}

need_cmd tar
need_cmd find
need_cmd sed

mkdir -p "$(dirname "$INSTALL_DIR")"
rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"

download "${REPO_URL}/archive/${REF}.tar.gz" "$ARCHIVE"
tar -xzf "$ARCHIVE" -C "$WORK_DIR"

EXTRACTED_DIR=$(find "$WORK_DIR" -mindepth 1 -maxdepth 1 -type d | sed -n '1p')
if [ -z "$EXTRACTED_DIR" ] || [ ! -f "${EXTRACTED_DIR}/install.sh" ]; then
  printf 'error: downloaded archive did not contain install.sh\n' >&2
  exit 1
fi

rm -rf "$INSTALL_DIR"
mv "$EXTRACTED_DIR" "$INSTALL_DIR"

"${INSTALL_DIR}/install.sh"

printf 'Source installed in: %s\n' "$INSTALL_DIR"
