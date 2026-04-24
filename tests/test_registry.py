from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ssh_auth.registry import (
    Profile,
    RegistryError,
    find_profiles,
    load_registry,
    profile_snapshot_path,
    remove_profiles,
    safe_profile_key,
    save_registry,
    set_active_profile,
    upsert_profile,
)


class RegistryTests(unittest.TestCase):
    def test_load_registry_returns_empty_registry_when_missing(self) -> None:
        with isolated_state_home() as tmp_path:
            registry = load_registry()

            self.assertEqual(registry.schema_version, 1)
            self.assertIsNone(registry.active_profile_key)
            self.assertEqual(registry.profiles, {})

    def test_upsert_save_load_and_profile_snapshot(self) -> None:
        with isolated_state_home():
            registry = load_registry()

            upsert_profile(
                registry,
                {
                    "key": "lab/gpu 01",
                    "alias": "lab-gpu",
                    "host": "10.0.0.5",
                    "user": "ubuntu",
                    "port": 2222,
                    "identity_file": "~/.ssh/id_ed25519",
                    "remote_path": "/home/ubuntu/work",
                    "proxy_jump": "bastion",
                    "forward_agent": True,
                    "tags": ["gpu", "cuda"],
                    "last_check_at": 123,
                    "last_check_ok": True,
                    "last_check_message": "OK",
                    "system_info": {"gpu": "A100 40.0GB", "memory": "125.8GB"},
                },
            )
            save_registry(registry)

            loaded = load_registry()
            profile = loaded.profiles["lab/gpu 01"]
            self.assertEqual(profile.alias, "lab-gpu")
            self.assertEqual(profile.port, 2222)
            self.assertIs(profile.forward_agent, True)
            self.assertEqual(profile.tags, ["gpu", "cuda"])
            self.assertEqual(profile.last_check_at, 123)
            self.assertIs(profile.last_check_ok, True)
            self.assertEqual(profile.last_check_message, "OK")
            self.assertEqual(profile.system_info, {"gpu": "A100 40.0GB", "memory": "125.8GB"})

            snapshot = profile_snapshot_path(profile.key)
            self.assertTrue(snapshot.exists())
            self.assertEqual(snapshot.name, f"{safe_profile_key(profile.key)}.json")
            self.assertNotIn("/", snapshot.name)
            self.assertEqual(json.loads(snapshot.read_text(encoding="utf-8"))["key"], profile.key)

    def test_set_active_profile_updates_last_used_and_rejects_missing(self) -> None:
        with isolated_state_home():
            registry = load_registry()
            upsert_profile(registry, profile_data("gpu01"))

            result = set_active_profile(registry, "gpu01")
            save_registry(registry)

            loaded = load_registry()
            self.assertIs(result, registry)
            self.assertGreater(registry.profiles["gpu01"].last_used_at, 0)
            self.assertEqual(loaded.active_profile_key, "gpu01")
            self.assertEqual(loaded.profiles["gpu01"].last_used_at, registry.profiles["gpu01"].last_used_at)

            with self.assertRaises(RegistryError):
                set_active_profile(registry, "missing")

    def test_remove_profiles_clears_active_and_removes_stale_snapshot(self) -> None:
        with isolated_state_home():
            registry = load_registry()
            upsert_profile(registry, profile_data("gpu01"))
            upsert_profile(registry, profile_data("gpu02"))
            set_active_profile(registry, "gpu01")
            save_registry(registry)

            stale_snapshot = profile_snapshot_path("gpu01")
            self.assertTrue(stale_snapshot.exists())

            result = remove_profiles(registry, ["gpu01", "missing"])
            save_registry(registry)
            loaded = load_registry()

            self.assertIs(result, registry)
            self.assertNotIn("gpu01", registry.profiles)
            self.assertIsNone(loaded.active_profile_key)
            self.assertIn("gpu02", loaded.profiles)
            self.assertFalse(stale_snapshot.exists())

    def test_save_registry_creates_at_most_five_backups(self) -> None:
        with isolated_state_home() as tmp_path:
            registry = load_registry()
            upsert_profile(registry, profile_data("gpu01"))
            save_registry(registry)

            for index in range(8):
                upsert_profile(registry, {**profile_data("gpu01"), "alias": f"gpu-{index}"})
                save_registry(registry)

            backups = sorted(tmp_path.glob("registry.json.bak.*"))
            self.assertEqual(len(backups), 5)
            self.assertTrue(all(path.read_text(encoding="utf-8") for path in backups))

    def test_find_profiles_fuzzy_matches_key_alias_host_user_path_and_tags(self) -> None:
        with isolated_state_home():
            registry = load_registry()
            upsert_profile(
                registry,
                {
                    **profile_data("gpu-prod"),
                    "alias": "lab-gpu",
                    "host": "10.0.0.8",
                    "user": "ubuntu",
                    "remote_path": "/srv/codex/project",
                    "tags": ["CUDA", "training"],
                },
            )
            upsert_profile(registry, {**profile_data("cpu-dev"), "alias": "plain-dev", "tags": ["backend"]})

            self.assertEqual([profile.key for profile in find_profiles(registry, "prod")], ["gpu-prod"])
            self.assertEqual([profile.key for profile in find_profiles(registry, "lab")], ["gpu-prod"])
            self.assertEqual([profile.key for profile in find_profiles(registry, "10.0")], ["gpu-prod"])
            self.assertEqual([profile.key for profile in find_profiles(registry, "UBU")], ["gpu-prod"])
            self.assertEqual([profile.key for profile in find_profiles(registry, "project")], ["gpu-prod"])
            self.assertEqual([profile.key for profile in find_profiles(registry, "cuda")], ["gpu-prod"])
            self.assertEqual([profile.key for profile in find_profiles(registry, None)], ["cpu-dev", "gpu-prod"])

    def test_profile_dataclass_can_be_upserted_directly(self) -> None:
        with isolated_state_home():
            registry = load_registry()
            profile = Profile(key="gpu01", alias="gpu01", host="example.com", user="root")

            upsert_profile(registry, profile)
            save_registry(registry)

            self.assertEqual(load_registry().profiles["gpu01"].host, "example.com")


def isolated_state_home():
    tempdir = tempfile.TemporaryDirectory()
    state_home = Path(tempdir.name)
    patcher = patch.dict(os.environ, {"SSH_AUTH_HOME": str(state_home)})

    class Context:
        def __enter__(self) -> Path:
            patcher.__enter__()
            return state_home

        def __exit__(self, exc_type, exc, tb) -> None:
            patcher.__exit__(exc_type, exc, tb)
            tempdir.cleanup()

    return Context()


def profile_data(key: str) -> dict[str, object]:
    return {
        "key": key,
        "alias": key,
        "host": f"{key}.example.com",
        "user": "dev",
        "port": 22,
        "identity_file": None,
        "remote_path": None,
        "proxy_jump": None,
        "forward_agent": False,
        "tags": [],
    }
