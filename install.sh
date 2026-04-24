#!/usr/bin/env sh
set -eu

APP_NAME=ssh-auth
SCRIPT_DIR=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
TARGET_DIR="${HOME}/.local/bin"
TARGET="${TARGET_DIR}/${APP_NAME}"
PATH_LINE="export PATH=\"\$HOME/.local/bin:\$PATH\""

if [ ! -x "${SCRIPT_DIR}/${APP_NAME}" ]; then
  printf 'error: expected executable %s next to install.sh\n' "${SCRIPT_DIR}/${APP_NAME}" >&2
  printf 'For remote installation, use install-remote.sh instead.\n' >&2
  exit 1
fi

mkdir -p "$TARGET_DIR"
ln -sf "${SCRIPT_DIR}/${APP_NAME}" "$TARGET"

case ":${PATH}:" in
  *":${TARGET_DIR}:"*) ;;
  *)
    SHELL_RC="${HOME}/.bashrc"
    if [ -n "${ZSH_VERSION:-}" ]; then
      SHELL_RC="${HOME}/.zshrc"
    fi
    if [ -f "$SHELL_RC" ]; then
      if ! grep -qxF "$PATH_LINE" "$SHELL_RC"; then
        printf '\n%s\n' "$PATH_LINE" >> "$SHELL_RC"
      fi
      printf 'Added %s to PATH in %s\n' "$TARGET_DIR" "$SHELL_RC"
      printf 'Run: source %s\n' "$SHELL_RC"
    else
      printf 'Add this to your shell profile:\n'
      printf '  %s\n' "$PATH_LINE"
    fi
    ;;
esac

printf 'Installed: %s -> %s\n' "$TARGET" "${SCRIPT_DIR}/${APP_NAME}"
printf 'Try: ssh-auth --help\n'
