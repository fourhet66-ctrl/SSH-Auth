from __future__ import annotations

import os
import shlex
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import is_dataclass
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from . import paths


MANAGED_HEADER = (
    "# This file is managed by ssh-auth.\n"
    "# Manual edits may be overwritten.\n"
)
INCLUDE_LINE = "Include ~/.ssh/config.d/*.config"
ACTIVE_ALIAS = "codex-active"

_ALIAS_FORBIDDEN_CHARS = set("*?!/\\")


def validate_alias(alias: str) -> str:
    """Validate and normalize a concrete OpenSSH Host alias."""
    if not isinstance(alias, str):
        raise ValueError("SSH host alias must be a string")

    normalized = alias.strip()
    if not normalized:
        raise ValueError("SSH host alias cannot be empty")
    if normalized.startswith("-"):
        raise ValueError(f"SSH host alias cannot start with '-': {alias!r}")
    if normalized != alias or any(char.isspace() for char in normalized):
        raise ValueError(f"SSH host alias cannot contain whitespace: {alias!r}")
    if any(char in _ALIAS_FORBIDDEN_CHARS for char in normalized):
        raise ValueError(
            "SSH host alias cannot contain wildcards, negation, or path separators: "
            f"{alias!r}"
        )
    return normalized


def ensure_include() -> bool:
    """Ensure the user SSH config includes ssh-auth's managed config directory.

    Returns True when the config file was changed, False when it already
    contained the include directive.
    """
    config_path = paths.ssh_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    paths.managed_config_path().parent.mkdir(parents=True, exist_ok=True)

    if not config_path.exists():
        _atomic_write(config_path, INCLUDE_LINE + "\n", mode=0o600)
        return True

    original = config_path.read_text(encoding="utf-8")
    if _has_include(original):
        return False

    _backup_config(config_path)
    if original:
        separator = "" if original.startswith("\n") else "\n"
        updated = INCLUDE_LINE + separator + original
    else:
        updated = INCLUDE_LINE + "\n"
    _atomic_write(config_path, updated, mode=_current_mode(config_path))
    return True


def parse_ssh_config_hosts(path: str | os.PathLike[str]) -> list[str]:
    """Parse concrete Host aliases from an OpenSSH config file.

    Pattern-style entries containing *, ?, or ! are ignored because they are
    not selectable concrete Codex remote aliases.
    """
    config_path = Path(path)
    if not config_path.exists():
        return []

    aliases: list[str] = []
    seen: set[str] = set()

    for line in config_path.read_text(encoding="utf-8").splitlines():
        try:
            tokens = shlex.split(line, comments=True, posix=True)
        except ValueError:
            continue
        if not tokens or tokens[0].lower() != "host":
            continue

        for candidate in tokens[1:]:
            if any(char in candidate for char in "*?!"):
                continue
            try:
                alias = validate_alias(candidate)
            except ValueError:
                continue
            if alias not in seen:
                seen.add(alias)
                aliases.append(alias)

    return aliases


def render_host_block(
    profile: Any,
    *,
    alias: str | None = None,
) -> str:
    """Render one managed OpenSSH Host block from a profile-like object."""
    host_alias = validate_alias(
        alias or _required_profile_value(profile, "alias", "host_alias", "name", "key", "Host")
    )
    directives = [f"Host {host_alias}"]

    hostname = _profile_value(profile, "hostname", "host_name", "host", "HostName")
    if hostname is not None:
        directives.append(f"  HostName {_format_value(hostname)}")

    rendered_fields = (
        ("User", _profile_value(profile, "user", "username", "User")),
        ("Port", _profile_value(profile, "port", "Port")),
        (
            "IdentityFile",
            _profile_value(profile, "identity_file", "identityFile", "key_file", "IdentityFile"),
        ),
        ("ProxyJump", _profile_value(profile, "proxy_jump", "proxyJump", "ProxyJump")),
        ("ForwardAgent", _profile_value(profile, "forward_agent", "forwardAgent", "ForwardAgent")),
        (
            "ServerAliveInterval",
            _profile_value(profile, "server_alive_interval", "serverAliveInterval", "ServerAliveInterval"),
        ),
        (
            "ServerAliveCountMax",
            _profile_value(profile, "server_alive_count_max", "serverAliveCountMax", "ServerAliveCountMax"),
        ),
    )

    for name, value in rendered_fields:
        if value is None:
            continue
        directives.append(f"  {name} {_format_value(value)}")

    return "\n".join(directives) + "\n"


def write_managed_config(active_profile: Any | None, profiles: Iterable[Any] | Mapping[str, Any]) -> Path:
    """Write ssh-auth's managed OpenSSH config file.

    Every profile is rendered under its own alias. The active profile is also
    rendered as the stable alias ``codex-active`` so Codex users can bind to a
    single name while switching the underlying target.
    """
    managed_path = paths.managed_config_path()
    managed_path.parent.mkdir(parents=True, exist_ok=True)

    profile_list = _coerce_profiles(profiles)
    active = _resolve_active_profile(active_profile, profile_list)

    blocks: list[str] = []
    for profile in profile_list:
        blocks.append(render_host_block(profile).rstrip())

    if active is not None:
        active_alias = _required_profile_value(active, "alias", "host_alias", "name", "key", "Host")
        if active_alias != ACTIVE_ALIAS:
            blocks.append(render_host_block(active, alias=ACTIVE_ALIAS).rstrip())

    body = MANAGED_HEADER
    if blocks:
        body += "\n" + "\n\n".join(blocks) + "\n"

    _atomic_write(managed_path, body, mode=0o600)
    return managed_path


def _has_include(content: str) -> bool:
    for line in content.splitlines():
        try:
            tokens = shlex.split(line, comments=True, posix=True)
        except ValueError:
            continue
        if len(tokens) == 2 and tokens[0].lower() == "include" and tokens[1] == "~/.ssh/config.d/*.config":
            return True
    return False


def _backup_config(config_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = config_path.with_name(f"{config_path.name}.bak.{timestamp}")
    backup_path = base
    suffix = 1
    while backup_path.exists():
        backup_path = config_path.with_name(f"{config_path.name}.bak.{timestamp}.{suffix}")
        suffix += 1
    shutil.copy2(config_path, backup_path)
    return backup_path


def _atomic_write(path: Path, content: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as temp_file:
        temp_file.write(content)
        temp_name = temp_file.name
    os.chmod(temp_name, mode)
    os.replace(temp_name, path)


def _current_mode(path: Path) -> int:
    try:
        return path.stat().st_mode & 0o777
    except FileNotFoundError:
        return 0o600


def _coerce_profiles(profiles: Iterable[Any] | Mapping[str, Any]) -> list[Any]:
    if isinstance(profiles, Mapping):
        return list(profiles.values())
    return list(profiles)


def _resolve_active_profile(active_profile: Any | None, profiles: list[Any]) -> Any | None:
    if active_profile is None:
        return None
    if isinstance(active_profile, str):
        for profile in profiles:
            candidates = (
                _profile_value(profile, "alias", "host_alias", "name", "key", "Host"),
                _profile_value(profile, "key"),
            )
            if any(active_profile == candidate for candidate in candidates):
                return profile
        raise ValueError(f"Unknown active SSH profile: {active_profile}")
    return active_profile


def _required_profile_value(profile: Any, *names: str) -> str:
    value = _profile_value(profile, *names)
    if value is None:
        raise ValueError(f"Profile is missing required field: {'/'.join(names)}")
    return str(value)


def _profile_value(profile: Any, *names: str) -> Any | None:
    if isinstance(profile, Mapping):
        for name in names:
            if name in profile and profile[name] is not None:
                return profile[name]
        return None

    if is_dataclass(profile):
        for name in names:
            if hasattr(profile, name):
                value = getattr(profile, name)
                if value is not None:
                    return value
        return None

    for name in names:
        if hasattr(profile, name):
            value = getattr(profile, name)
            if value is not None:
                return value
    return None


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        text = "yes" if value else "no"
    else:
        text = str(value)
    if not text:
        return '""'
    if any(char.isspace() for char in text) or "#" in text:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text
