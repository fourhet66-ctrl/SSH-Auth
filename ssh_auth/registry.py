from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .paths import profiles_dir, registry_path


SCHEMA_VERSION = 1
MAX_REGISTRY_BACKUPS = 5


class RegistryError(RuntimeError):
    """Raised when the ssh-auth registry cannot be loaded or written."""


@dataclass
class Profile:
    key: str
    alias: str
    host: str
    user: str
    port: int = 22
    identity_file: str | None = None
    remote_path: str | None = None
    proxy_jump: str | None = None
    forward_agent: bool = False
    tags: list[str] = field(default_factory=list)
    created_at: int = 0
    last_used_at: int = 0
    last_check_at: int = 0
    last_check_ok: bool | None = None
    last_check_message: str | None = None
    system_info: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "Profile":
        now = _now()
        key = _required_str(data, "key")
        alias = _optional_str(data.get("alias")) or key
        host = _required_str(data, "host")
        user = _required_str(data, "user")
        port = int(data.get("port") or 22)
        if port <= 0 or port > 65535:
            raise RegistryError(f"profile {key!r} has invalid port: {port}")

        tags_value = data.get("tags") or []
        if not isinstance(tags_value, list) or not all(isinstance(tag, str) for tag in tags_value):
            raise RegistryError(f"profile {key!r} tags must be a list of strings")
        system_info_value = data.get("system_info") or {}
        if not isinstance(system_info_value, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in system_info_value.items()
        ):
            raise RegistryError(f"profile {key!r} system_info must be an object with string values")

        return cls(
            key=key,
            alias=alias,
            host=host,
            user=user,
            port=port,
            identity_file=_optional_str(data.get("identity_file")),
            remote_path=_optional_str(data.get("remote_path")),
            proxy_jump=_optional_str(data.get("proxy_jump")),
            forward_agent=bool(data.get("forward_agent", False)),
            tags=list(tags_value),
            created_at=int(data.get("created_at") or now),
            last_used_at=int(data.get("last_used_at") or 0),
            last_check_at=int(data.get("last_check_at") or 0),
            last_check_ok=data.get("last_check_ok") if isinstance(data.get("last_check_ok"), bool) else None,
            last_check_message=_optional_str(data.get("last_check_message")),
            system_info=dict(system_info_value),
        )

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Registry:
    schema_version: int = SCHEMA_VERSION
    active_profile_key: str | None = None
    profiles: dict[str, Profile] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "active_profile_key": self.active_profile_key,
            "profiles": [profile.to_json() for profile in sorted(self.profiles.values(), key=lambda item: item.key)],
        }


def load_registry(path: Path | None = None) -> Registry:
    registry_file = path or registry_path()
    if not registry_file.exists():
        return Registry()

    try:
        with registry_file.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except OSError as exc:
        raise RegistryError(f"failed to read registry: {registry_file}") from exc
    except json.JSONDecodeError as exc:
        raise RegistryError(f"registry is not valid JSON: {registry_file}") from exc

    if not isinstance(raw, dict):
        raise RegistryError("registry root must be a JSON object")
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise RegistryError(f"unsupported registry schema_version: {raw.get('schema_version')!r}")

    loaded_profiles = raw.get("profiles") or []
    if isinstance(loaded_profiles, dict):
        loaded_profiles = list(loaded_profiles.values())
    if not isinstance(loaded_profiles, list):
        raise RegistryError("registry profiles must be a list")

    registry = Registry(schema_version=SCHEMA_VERSION)
    for item in loaded_profiles:
        if not isinstance(item, dict):
            raise RegistryError("registry profile entries must be objects")
        profile = Profile.from_mapping(item)
        registry.profiles[profile.key] = profile

    active = raw.get("active_profile_key")
    registry.active_profile_key = active if isinstance(active, str) and active in registry.profiles else None
    return registry


def save_registry(
    registry: Registry,
    path: Path | None = None,
    *,
    backup: bool = True,
    write_profile_snapshots: bool = True,
) -> None:
    registry_file = path or registry_path()
    if registry.schema_version != SCHEMA_VERSION:
        raise RegistryError(f"unsupported registry schema_version: {registry.schema_version!r}")
    if registry.active_profile_key is not None and registry.active_profile_key not in registry.profiles:
        raise RegistryError(f"active profile does not exist: {registry.active_profile_key}")

    registry_file.parent.mkdir(parents=True, exist_ok=True)
    _chmod_private_dir(registry_file.parent)

    payload = registry.to_json()
    if registry_file.exists() and _json_file_equals(registry_file, payload):
        os.chmod(registry_file, 0o600)
        if write_profile_snapshots:
            _write_profile_snapshots(registry, registry_file)
        return

    if backup and registry_file.exists():
        _create_registry_backup(registry_file)

    _atomic_write_json(registry_file, payload)

    if write_profile_snapshots:
        _write_profile_snapshots(registry, registry_file)


def upsert_profile(registry: Registry, profile: Profile | Mapping[str, Any]) -> Registry:
    incoming = profile if isinstance(profile, Profile) else Profile.from_mapping(profile)
    existing = registry.profiles.get(incoming.key)
    if existing and not incoming.created_at:
        incoming.created_at = existing.created_at
    elif existing:
        incoming.created_at = existing.created_at
    if not incoming.created_at:
        incoming.created_at = _now()

    registry.profiles[incoming.key] = incoming
    return registry


def remove_profiles(registry: Registry, keys: Iterable[str]) -> Registry:
    for key in keys:
        profile = registry.profiles.pop(key, None)
        if profile is not None:
            if registry.active_profile_key == key:
                registry.active_profile_key = None
    return registry


def set_active_profile(registry: Registry, key: str | None) -> Registry:
    if key is None:
        registry.active_profile_key = None
        return registry
    if key not in registry.profiles:
        raise RegistryError(f"profile does not exist: {key}")
    registry.active_profile_key = key
    profile = registry.profiles[key]
    profile.last_used_at = _now()
    return registry


def find_profiles(registry: Registry, query: str | None = None) -> list[Profile]:
    profiles = list(registry.profiles.values())
    if not query:
        return sorted(profiles, key=lambda item: item.key)

    needle = query.casefold()
    matches: list[tuple[int, str, Profile]] = []
    for profile in profiles:
        fields = _search_fields(profile)
        score = _match_score(needle, fields)
        if score:
            matches.append((score, profile.key, profile))
    matches.sort(key=lambda item: (-item[0], item[1]))
    return [profile for _, _, profile in matches]


def safe_profile_key(key: str) -> str:
    if not key:
        raise RegistryError("profile key is required")
    encoded = base64.urlsafe_b64encode(key.encode("utf-8")).decode("ascii").rstrip("=")
    return encoded or "_"


def profile_snapshot_path(key: str, base_dir: Path | None = None) -> Path:
    root = base_dir or profiles_dir()
    return root / f"{safe_profile_key(key)}.json"


def _write_profile_snapshots(registry: Registry, registry_file: Path) -> None:
    root = registry_file.parent / "profiles"
    root.mkdir(parents=True, exist_ok=True)
    _chmod_private_dir(root)

    expected = {profile_snapshot_path(key, root) for key in registry.profiles}
    for profile in registry.profiles.values():
        _atomic_write_json(profile_snapshot_path(profile.key, root), profile.to_json())

    for existing in root.glob("*.json"):
        if existing not in expected:
            existing.unlink()


def _create_registry_backup(registry_file: Path) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = registry_file.with_name(f"{registry_file.name}.bak.{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = registry_file.with_name(f"{registry_file.name}.bak.{timestamp}.{counter}")
        counter += 1

    shutil.copy2(registry_file, candidate)
    os.chmod(candidate, 0o600)
    _prune_registry_backups(registry_file)


def _prune_registry_backups(registry_file: Path) -> None:
    backups = sorted(
        registry_file.parent.glob(f"{registry_file.name}.bak.*"),
        key=lambda item: (item.stat().st_mtime_ns, item.name),
        reverse=True,
    )
    for stale in backups[MAX_REGISTRY_BACKUPS:]:
        stale.unlink()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_name = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except OSError as exc:
        if tmp_name:
            try:
                Path(tmp_name).unlink(missing_ok=True)
            except OSError:
                pass
        raise RegistryError(f"failed to write JSON file: {path}") from exc


def _json_file_equals(path: Path, payload: Mapping[str, Any]) -> bool:
    try:
        existing = path.read_text(encoding="utf-8")
    except OSError:
        return False
    expected = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return existing == expected


def _search_fields(profile: Profile) -> list[str]:
    fields = [
        profile.key,
        profile.alias,
        profile.host,
        profile.user,
        str(profile.port),
        profile.identity_file or "",
        profile.remote_path or "",
        profile.proxy_jump or "",
    ]
    fields.extend(profile.tags)
    return [field.casefold() for field in fields if field]


def _match_score(needle: str, fields: list[str]) -> int:
    score = 0
    for field_value in fields:
        if field_value == needle:
            score = max(score, 100)
        elif field_value.startswith(needle):
            score = max(score, 75)
        elif needle in field_value:
            score = max(score, 50)
    return score


def _required_str(data: Mapping[str, Any], field_name: str) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"profile {field_name} is required")
    return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RegistryError(f"expected string or null, got {type(value).__name__}")
    return value or None


def _chmod_private_dir(path: Path) -> None:
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _now() -> int:
    return int(time.time())
