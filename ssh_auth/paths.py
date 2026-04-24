from __future__ import annotations

import os
from pathlib import Path


def user_home() -> Path:
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    if not home:
        raise RuntimeError("HOME or USERPROFILE is required")
    return Path(home).expanduser()


def codex_home() -> Path:
    override = os.environ.get("CODEX_HOME")
    if override:
        path = Path(override).expanduser()
        if not path.exists():
            raise RuntimeError(f"CODEX_HOME points to a missing path: {path}")
        if not path.is_dir():
            raise RuntimeError(f"CODEX_HOME is not a directory: {path}")
        return path
    return user_home() / ".codex"


def state_home() -> Path:
    override = os.environ.get("SSH_AUTH_HOME")
    if override:
        return Path(override).expanduser()
    return codex_home() / "ssh-auth"


def ssh_dir() -> Path:
    override = os.environ.get("SSH_AUTH_SSH_DIR")
    if override:
        return Path(override).expanduser()
    return user_home() / ".ssh"


def registry_path() -> Path:
    return state_home() / "registry.json"


def profiles_dir() -> Path:
    return state_home() / "profiles"


def managed_config_path() -> Path:
    return ssh_dir() / "config.d" / "codex-ssh-auth.config"


def ssh_config_path() -> Path:
    return ssh_dir() / "config"


def codex_config_path() -> Path:
    return codex_home() / "config.toml"
