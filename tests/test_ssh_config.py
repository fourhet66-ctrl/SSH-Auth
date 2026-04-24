from __future__ import annotations

import os
import re
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from ssh_auth import paths
from ssh_auth.ssh_config import (
    ACTIVE_ALIAS,
    INCLUDE_LINE,
    ensure_include,
    parse_ssh_config_hosts,
    render_host_block,
    validate_alias,
    write_managed_config,
)


class SshConfigTests(unittest.TestCase):
    def test_ensure_include_inserts_once_and_backs_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ssh_dir = Path(tmp_dir) / ".ssh"
            ssh_dir.mkdir()
            config_path = ssh_dir / "config"
            config_path.write_text("Host existing\n  HostName example.com\n", encoding="utf-8")

            with mock.patch.dict(os.environ, {"SSH_AUTH_SSH_DIR": str(ssh_dir)}):
                self.assertTrue(ensure_include())

                updated = config_path.read_text(encoding="utf-8")
                self.assertTrue(updated.startswith(INCLUDE_LINE + "\n"))
                self.assertIn("Host existing\n  HostName example.com\n", updated)

                backups = list(ssh_dir.glob("config.bak.*"))
                self.assertEqual(len(backups), 1)
                self.assertRegex(backups[0].name, r"config\.bak\.\d{8}-\d{6}(?:\.\d+)?")
                self.assertEqual(
                    backups[0].read_text(encoding="utf-8"),
                    "Host existing\n  HostName example.com\n",
                )

                self.assertFalse(ensure_include())
                self.assertEqual(config_path.read_text(encoding="utf-8"), updated)
                self.assertEqual(len(list(ssh_dir.glob("config.bak.*"))), 1)

    def test_ensure_include_creates_missing_config_without_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ssh_dir = Path(tmp_dir) / ".ssh"

            with mock.patch.dict(os.environ, {"SSH_AUTH_SSH_DIR": str(ssh_dir)}):
                self.assertTrue(ensure_include())

                self.assertEqual(
                    (ssh_dir / "config").read_text(encoding="utf-8"),
                    INCLUDE_LINE + "\n",
                )
                self.assertTrue((ssh_dir / "config.d").is_dir())
                self.assertEqual(list(ssh_dir.glob("config.bak.*")), [])

    def test_render_host_block_from_dict(self) -> None:
        block = render_host_block(
            {
                "alias": "gpu01",
                "host": "10.0.0.7",
                "user": "ubuntu",
                "port": 2222,
                "identity_file": "~/.ssh/id_ed25519",
                "proxy_jump": "bastion",
                "forward_agent": True,
                "server_alive_interval": 30,
                "server_alive_count_max": 3,
            }
        )

        self.assertEqual(
            block,
            "Host gpu01\n"
            "  HostName 10.0.0.7\n"
            "  User ubuntu\n"
            "  Port 2222\n"
            "  IdentityFile ~/.ssh/id_ed25519\n"
            "  ProxyJump bastion\n"
            "  ForwardAgent yes\n"
            "  ServerAliveInterval 30\n"
            "  ServerAliveCountMax 3\n",
        )

    def test_render_host_block_from_openssh_style_dict(self) -> None:
        block = render_host_block(
            {
                "Host": "gpu01",
                "HostName": "10.0.0.7",
                "User": "ubuntu",
                "Port": 2222,
                "IdentityFile": "~/.ssh/id_ed25519",
                "ProxyJump": "bastion",
                "ForwardAgent": "yes",
                "ServerAliveInterval": 30,
                "ServerAliveCountMax": 3,
            }
        )

        self.assertEqual(
            block,
            "Host gpu01\n"
            "  HostName 10.0.0.7\n"
            "  User ubuntu\n"
            "  Port 2222\n"
            "  IdentityFile ~/.ssh/id_ed25519\n"
            "  ProxyJump bastion\n"
            "  ForwardAgent yes\n"
            "  ServerAliveInterval 30\n"
            "  ServerAliveCountMax 3\n",
        )

    def test_write_managed_config_renders_all_profiles_and_active_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            ssh_dir = Path(tmp_dir) / ".ssh"

            with mock.patch.dict(os.environ, {"SSH_AUTH_SSH_DIR": str(ssh_dir)}):
                managed_path = write_managed_config(
                    "gpu02",
                    [
                        {"alias": "gpu01", "host": "10.0.0.1", "user": "ubuntu"},
                        {
                            "alias": "gpu02",
                            "host": "10.0.0.2",
                            "user": "root",
                            "forward_agent": False,
                        },
                    ],
                )

                self.assertEqual(managed_path, paths.managed_config_path())
                content = managed_path.read_text(encoding="utf-8")

        self.assertIn("# This file is managed by ssh-auth.", content)
        self.assertIn("Host gpu01\n  HostName 10.0.0.1\n  User ubuntu\n", content)
        self.assertIn(
            "Host gpu02\n  HostName 10.0.0.2\n  User root\n  ForwardAgent no\n",
            content,
        )
        self.assertIn(
            f"Host {ACTIVE_ALIAS}\n  HostName 10.0.0.2\n  User root\n  ForwardAgent no\n",
            content,
        )

    def test_render_host_block_from_dataclass(self) -> None:
        block = render_host_block(DataclassProfile("lab", "lab.example.com", "alice", 22))

        self.assertEqual(
            block,
            "Host lab\n"
            "  HostName lab.example.com\n"
            "  User alice\n"
            "  Port 22\n",
        )

    def test_parse_ssh_config_hosts_skips_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config"
            config_path.write_text(
                """
# comment
Host gpu01 prod-*
  HostName 10.0.0.1

Host *
  ServerAliveInterval 30

Host !blocked gpu02 "quoted-alias"
  User ubuntu

Host bad/path
  HostName ignored
""",
                encoding="utf-8",
            )

            self.assertEqual(
                parse_ssh_config_hosts(config_path),
                ["gpu01", "gpu02", "quoted-alias"],
            )

    def test_validate_alias_rejects_invalid_aliases(self) -> None:
        for alias in (
            "",
            "  ",
            "gpu 01",
            " gpu01",
            "gpu01\n",
            "prod-*",
            "host?",
            "!blocked",
            "-oProxyCommand=bad",
            "dir/name",
            r"dir\name",
        ):
            with self.subTest(alias=alias):
                with self.assertRaises(ValueError):
                    validate_alias(alias)

    def test_validate_alias_accepts_concrete_alias(self) -> None:
        self.assertEqual(validate_alias("gpu-01.example"), "gpu-01.example")


@dataclass
class DataclassProfile:
    alias: str
    hostname: str
    username: str
    port: int


if __name__ == "__main__":
    unittest.main()
