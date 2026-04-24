from __future__ import annotations

import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ssh_auth import cli
from ssh_auth.codex_config import enable_remote_control


class CliTests(unittest.TestCase):
    def test_add_calls_registry_and_writes_config(self) -> None:
        registry = {"profiles": [], "active_profile_key": None}
        calls: list[tuple[str, object]] = []

        def upsert(reg, profile):
            calls.append(("upsert", profile))
            reg["profiles"].append(profile)
            return reg

        with (
            mock.patch.object(cli, "load_registry", return_value=registry),
            mock.patch.object(cli, "save_registry", side_effect=lambda reg: calls.append(("save", reg))),
            mock.patch.object(cli, "ensure_include", side_effect=lambda: calls.append(("include", None))),
            mock.patch.object(cli, "write_managed_config", side_effect=lambda reg: calls.append(("write", reg))),
            mock.patch.object(cli, "upsert_profile", side_effect=upsert),
        ):
            rc, stdout, _ = run_cli(
                [
                    "add",
                    "gpu01",
                    "--host",
                    "10.0.0.1",
                    "--user",
                    "ubuntu",
                    "--port",
                    "2222",
                    "--key",
                    "~/.ssh/id_ed25519",
                    "--remote-path",
                    "/work/repo",
                ]
            )

        self.assertEqual(rc, 0)
        self.assertIn(("save", registry), calls)
        self.assertIn(("include", None), calls)
        self.assertIn(("write", registry), calls)
        upserted = [value for name, value in calls if name == "upsert"][0]
        self.assertEqual(
            upserted,
            {
                "key": "gpu01",
                "alias": "gpu01",
                "host": "10.0.0.1",
                "user": "ubuntu",
                "port": 2222,
                "identity_file": "~/.ssh/id_ed25519",
                "remote_path": "/work/repo",
                "forward_agent": False,
            },
        )
        self.assertIn("Added gpu01.", stdout)

    def test_add_prompts_for_missing_fields(self) -> None:
        registry = {"profiles": [], "active_profile_key": None}
        calls: list[tuple[str, object]] = []

        def upsert(reg, profile):
            calls.append(("upsert", profile))
            reg["profiles"].append(profile)
            return reg

        prompts = iter(
            [
                "",  # no login command
                "",  # alias defaults to profile name
                "10.0.0.1",
                "ubuntu",
                "2222",
                "~/.ssh/id_ed25519",
                "/work/repo",
                "",
                "y",
                "n",
            ]
        )

        with (
            mock.patch.object(cli, "_can_prompt", return_value=True),
            mock.patch.object(cli, "_default_identity_file", return_value=None),
            mock.patch("builtins.input", side_effect=lambda _prompt: next(prompts)),
            mock.patch.object(cli, "load_registry", return_value=registry),
            mock.patch.object(cli, "save_registry", side_effect=lambda reg: calls.append(("save", reg))),
            mock.patch.object(cli, "ensure_include", side_effect=lambda: calls.append(("include", None))),
            mock.patch.object(cli, "write_managed_config", side_effect=lambda reg: calls.append(("write", reg))),
            mock.patch.object(cli, "upsert_profile", side_effect=upsert),
        ):
            rc, stdout, _ = run_cli(["add", "gpu01"])

        self.assertEqual(rc, 0)
        upserted = [value for name, value in calls if name == "upsert"][0]
        self.assertEqual(
            upserted,
            {
                "key": "gpu01",
                "alias": "gpu01",
                "host": "10.0.0.1",
                "user": "ubuntu",
                "port": 2222,
                "identity_file": "~/.ssh/id_ed25519",
                "remote_path": "/work/repo",
                "forward_agent": True,
            },
        )
        self.assertIn("Adding SSH profile: gpu01", stdout)
        self.assertIn("Added gpu01.", stdout)

    def test_add_parses_login_command_and_sets_up_key(self) -> None:
        registry = {"profiles": [], "active_profile_key": None}
        calls: list[tuple[str, object]] = []

        def upsert(reg, profile):
            calls.append(("upsert", profile))
            reg["profiles"].append(profile)
            return reg

        with (
            mock.patch.object(cli, "load_registry", return_value=registry),
            mock.patch.object(cli, "save_registry", side_effect=lambda reg: calls.append(("save", reg))),
            mock.patch.object(cli, "ensure_include", side_effect=lambda: calls.append(("include", None))),
            mock.patch.object(cli, "write_managed_config", side_effect=lambda reg: calls.append(("write", reg))),
            mock.patch.object(cli, "upsert_profile", side_effect=upsert),
            mock.patch.object(cli, "_setup_passwordless_login", side_effect=lambda profile: calls.append(("setup", profile.copy()))),
        ):
            rc, stdout, _ = run_cli(
                [
                    "add",
                    "gpu01",
                    "--login",
                    "ssh -i ~/.ssh/gpu_key -p 2222 ubuntu@10.0.0.1",
                    "--setup-key",
                ]
            )

        self.assertEqual(rc, 0)
        setup_profile = [value for name, value in calls if name == "setup"][0]
        self.assertEqual(setup_profile["host"], "10.0.0.1")
        self.assertEqual(setup_profile["user"], "ubuntu")
        self.assertEqual(setup_profile["port"], 2222)
        self.assertEqual(setup_profile["identity_file"], "~/.ssh/gpu_key")
        self.assertIs(setup_profile["_generate_key"], False)
        self.assertIn("Added gpu01.", stdout)

    def test_setup_key_requires_generate_key_for_missing_private_key(self) -> None:
        with (
            mock.patch.object(cli, "_default_identity_file", return_value=None),
            mock.patch("os.path.exists", return_value=False),
        ):
            with self.assertRaisesRegex(ValueError, "pass --generate-key"):
                cli._setup_passwordless_login({"host": "10.0.0.1", "user": "ubuntu", "_generate_key": False})

    def test_parse_ssh_login_command(self) -> None:
        self.assertEqual(
            cli.parse_ssh_login_command("ssh -J jumpbox -i ~/.ssh/key -p 2200 ubuntu@1.2.3.4"),
            {
                "proxy_jump": "jumpbox",
                "identity_file": "~/.ssh/key",
                "port": 2200,
                "user": "ubuntu",
                "host": "1.2.3.4",
            },
        )

    def test_add_requires_host_and_user_without_tty(self) -> None:
        with mock.patch.object(cli, "_can_prompt", return_value=False):
            rc, _, stderr = run_cli(["add", "gpu01"])

        self.assertEqual(rc, 1)
        self.assertIn("add requires --host and --user", stderr)

    def test_add_rejects_option_like_profile_alias_host_and_user(self) -> None:
        cases = [
            ["add", "--host", "10.0.0.1", "--user", "ubuntu", "--", "-bad"],
            ["add", "gpu01", "--alias=-bad", "--host", "10.0.0.1", "--user", "ubuntu"],
            ["add", "gpu01", "--host=-oProxyCommand=bad", "--user", "ubuntu"],
            ["add", "gpu01", "--host", "10.0.0.1", "--user=-oProxyCommand=bad"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                rc, _, stderr = run_cli(argv)
                self.assertEqual(rc, 1)
                self.assertTrue("invalid SSH" in stderr or "cannot start with '-'" in stderr)

    def test_list_marks_active_profile(self) -> None:
        registry = {
            "active_profile_key": "gpu01",
            "profiles": [
                {
                    "key": "gpu01",
                    "alias": "gpu",
                    "host": "10.0.0.1",
                    "user": "ubuntu",
                    "port": 22,
                    "last_check_ok": True,
                    "last_check_at": 9999999999,
                    "system_info": {"gpu": "A100 40.0GB", "memory": "125.8GB"},
                },
                {"key": "staging", "alias": "staging", "host": "10.0.0.2"},
            ],
        }

        def find(reg, selector=None):
            if selector is None:
                return reg["profiles"]
            return [profile for profile in reg["profiles"] if selector in profile["key"]]

        with (
            mock.patch.object(cli, "load_registry", return_value=registry),
            mock.patch.object(cli, "find_profiles", side_effect=find),
        ):
            rc, stdout, _ = run_cli(["list"])

        self.assertEqual(rc, 0)
        self.assertIn("PROFILE", stdout)
        self.assertIn("STATUS", stdout)
        self.assertIn("LAST CHECK", stdout)
        self.assertIn("RESOURCES", stdout)
        self.assertIn("* 01 gpu01 (gpu)", stdout)
        self.assertIn("ubuntu@10.0.0.1:22", stdout)
        self.assertIn("OK", stdout)
        self.assertIn("GPU A100 40.0GB; RAM 125.8GB", stdout)
        self.assertIn("  02 staging", stdout)

    def test_list_mentions_when_no_active_profile(self) -> None:
        registry = {
            "active_profile_key": None,
            "profiles": [{"key": "gpu01", "alias": "gpu01", "host": "10.0.0.1"}],
        }

        with (
            mock.patch.object(cli, "load_registry", return_value=registry),
            mock.patch.object(cli, "find_profiles", return_value=registry["profiles"]),
        ):
            rc, stdout, _ = run_cli(["list"])

        self.assertEqual(rc, 0)
        self.assertIn("  01 gpu01", stdout)
        self.assertIn("No active profile", stdout)

    def test_switch_sets_active_and_writes_config(self) -> None:
        registry = {
            "active_profile_key": None,
            "profiles": [{"key": "gpu01", "alias": "gpu", "host": "10.0.0.1"}],
        }
        calls: list[str] = []

        def set_active(reg, key):
            calls.append(f"active:{key}")
            reg["active_profile_key"] = key
            return reg

        with (
            mock.patch.object(cli, "load_registry", return_value=registry),
            mock.patch.object(cli, "find_profiles", return_value=registry["profiles"]),
            mock.patch.object(cli, "save_registry", side_effect=lambda reg: calls.append("save")),
            mock.patch.object(cli, "write_managed_config", side_effect=lambda reg: calls.append("write")),
            mock.patch.object(cli, "set_active_profile", side_effect=set_active),
        ):
            rc, stdout, _ = run_cli(["switch", "gpu"])

        self.assertEqual(rc, 0)
        self.assertEqual(registry["active_profile_key"], "gpu01")
        self.assertEqual(calls, ["active:gpu01", "save", "write"])
        self.assertIn("Switched to gpu01.", stdout)

    def test_status_shows_active_profile(self) -> None:
        registry = {
            "active_profile_key": "gpu01",
            "profiles": [{"key": "gpu01", "alias": "gpu", "host": "10.0.0.1"}],
        }

        with (
            mock.patch.object(cli, "load_registry", return_value=registry),
            mock.patch.object(cli, "find_profiles", return_value=registry["profiles"]),
        ):
            rc, stdout, _ = run_cli(["status"])

        self.assertEqual(rc, 0)
        self.assertIn("Active: gpu01 (gpu) -> 10.0.0.1", stdout)

    def test_config_remote_enable_preserves_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "config.toml"
            path.write_text('[model]\nname = "gpt-5"\n\n[features]\nremote_control = false # old\n', encoding="utf-8")

            enable_remote_control(path)

            self.assertEqual(
                path.read_text(encoding="utf-8"),
                '[model]\nname = "gpt-5"\n\n[features]\nremote_control = true # old\n',
            )

    def test_config_remote_enable_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "config.toml"
            with mock.patch.object(cli.paths, "codex_config_path", return_value=path):
                rc, stdout, _ = run_cli(["config", "remote", "enable"])

            self.assertEqual(rc, 0)
            self.assertIn("[features]\nremote_control = true\n", path.read_text(encoding="utf-8"))
            self.assertIn(f"Enabled Codex remote control: {path}", stdout)

    def test_test_command_uses_ssh_helpers(self) -> None:
        registry = {
            "active_profile_key": "gpu01",
            "profiles": [{"key": "gpu01", "alias": "gpu", "host": "10.0.0.1"}],
        }
        calls: list[tuple[str, str]] = []

        def run_config(alias):
            calls.append(("config", alias))
            return subprocess.CompletedProcess(["ssh", "-G", alias], 0, "", "")

        def run_batch(alias):
            calls.append(("batch", alias))
            return subprocess.CompletedProcess(["ssh", alias, "true"], 0, "", "")

        with (
            mock.patch.object(cli, "load_registry", return_value=registry),
            mock.patch.object(cli, "find_profiles", return_value=registry["profiles"]),
            mock.patch.object(cli, "run_ssh_config", side_effect=run_config),
            mock.patch.object(cli, "run_ssh_batch", side_effect=run_batch),
            mock.patch.object(cli, "run_ssh_info", return_value=subprocess.CompletedProcess(["ssh"], 0, "memory=125.8GB\ngpu=A100 40.0GB\n", "")),
            mock.patch.object(cli, "save_registry"),
        ):
            rc, stdout, _ = run_cli(["test"])

        self.assertEqual(rc, 0)
        self.assertEqual(calls, [("config", "gpu"), ("batch", "gpu")])
        self.assertIn("OK gpu.", stdout)
        self.assertTrue(registry["profiles"][0]["last_check_ok"])
        self.assertEqual(registry["profiles"][0]["system_info"]["gpu"], "A100 40.0GB")

    def test_check_all_checks_every_profile_and_reports_failure(self) -> None:
        registry = {
            "active_profile_key": "gpu01",
            "profiles": [
                {"key": "gpu01", "alias": "gpu", "host": "10.0.0.1"},
                {"key": "bad01", "alias": "bad", "host": "10.0.0.2"},
            ],
        }
        calls: list[tuple[str, str]] = []

        def run_config(alias):
            calls.append(("config", alias))
            return subprocess.CompletedProcess(["ssh", "-G", alias], 0, "", "")

        def run_batch(alias):
            calls.append(("batch", alias))
            code = 1 if alias == "bad" else 0
            return subprocess.CompletedProcess(["ssh", alias, "true"], code, "", "denied")

        with (
            mock.patch.object(cli, "load_registry", return_value=registry),
            mock.patch.object(cli, "find_profiles", return_value=registry["profiles"]),
            mock.patch.object(cli, "run_ssh_config", side_effect=run_config),
            mock.patch.object(cli, "run_ssh_batch", side_effect=run_batch),
            mock.patch.object(cli, "run_ssh_info", return_value=subprocess.CompletedProcess(["ssh"], 0, "memory=125.8GB\n", "")),
            mock.patch.object(cli, "save_registry"),
        ):
            rc, stdout, stderr = run_cli(["check", "--all"])

        self.assertEqual(rc, 1)
        self.assertEqual(calls, [("config", "gpu"), ("batch", "gpu"), ("config", "bad"), ("batch", "bad")])
        self.assertIn("OK gpu.", stdout)
        self.assertIn("FAIL bad: ssh connection failed: denied", stderr)
        self.assertTrue(registry["profiles"][0]["last_check_ok"])
        self.assertFalse(registry["profiles"][1]["last_check_ok"])

    def test_check_all_rejects_selector(self) -> None:
        rc, _, stderr = run_cli(["check", "--all", "gpu01"])

        self.assertEqual(rc, 1)
        self.assertIn("--all cannot be combined", stderr)

    def test_check_list_prints_profiles(self) -> None:
        registry = {
            "active_profile_key": None,
            "profiles": [{"key": "gpu01", "alias": "gpu01", "host": "10.0.0.1"}],
        }

        with (
            mock.patch.object(cli, "load_registry", return_value=registry),
            mock.patch.object(cli, "find_profiles", return_value=registry["profiles"]),
        ):
            rc, stdout, stderr = run_cli(["check", "list"])

        self.assertEqual(rc, 0)
        self.assertIn("PROFILE", stdout)
        self.assertIn("gpu01", stdout)
        self.assertEqual(stderr, "")

    def test_check_accepts_row_number(self) -> None:
        registry = {
            "active_profile_key": None,
            "profiles": [
                {"key": "gpu01", "alias": "gpu01", "host": "10.0.0.1"},
                {"key": "gpu02", "alias": "gpu02", "host": "10.0.0.2"},
            ],
        }
        calls: list[str] = []

        with (
            mock.patch.object(cli, "load_registry", return_value=registry),
            mock.patch.object(cli, "find_profiles", side_effect=lambda reg, selector=None: reg["profiles"] if selector is None else []),
            mock.patch.object(cli, "run_ssh_config", side_effect=lambda alias: calls.append(alias) or subprocess.CompletedProcess(["ssh"], 0, "", "")),
            mock.patch.object(cli, "run_ssh_batch", return_value=subprocess.CompletedProcess(["ssh"], 0, "", "")),
            mock.patch.object(cli, "run_ssh_info", return_value=subprocess.CompletedProcess(["ssh"], 0, "", "")),
            mock.patch.object(cli, "save_registry"),
        ):
            rc, stdout, _ = run_cli(["check", "02"])

        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["gpu02"])
        self.assertIn("OK gpu02.", stdout)

    def test_check_prompts_when_ambiguous(self) -> None:
        registry = {
            "active_profile_key": None,
            "profiles": [
                {"key": "gpu01-4090", "alias": "gpu01-4090", "host": "10.0.0.1"},
                {"key": "gpu02-A800", "alias": "gpu02-A800", "host": "10.0.0.2"},
            ],
        }

        def find(reg, selector=None):
            if selector is None:
                return reg["profiles"]
            return [profile for profile in reg["profiles"] if selector.casefold() in profile["key"].casefold()]

        with (
            mock.patch.object(cli, "_can_prompt", return_value=True),
            mock.patch("builtins.input", return_value="02"),
            mock.patch.object(cli, "load_registry", return_value=registry),
            mock.patch.object(cli, "find_profiles", side_effect=find),
            mock.patch.object(cli, "run_ssh_config", return_value=subprocess.CompletedProcess(["ssh"], 0, "", "")),
            mock.patch.object(cli, "run_ssh_batch", return_value=subprocess.CompletedProcess(["ssh"], 0, "", "")),
            mock.patch.object(cli, "run_ssh_info", return_value=subprocess.CompletedProcess(["ssh"], 0, "", "")),
            mock.patch.object(cli, "save_registry"),
        ):
            rc, stdout, _ = run_cli(["check", "gpu"])

        self.assertEqual(rc, 0)
        self.assertIn("ambiguous profile gpu. Select a profile", stdout)
        self.assertIn("OK gpu02-A800.", stdout)

    def test_check_without_active_prompts_for_profile(self) -> None:
        registry = {
            "active_profile_key": None,
            "profiles": [{"key": "gpu01", "alias": "gpu01", "host": "10.0.0.1"}],
        }

        with (
            mock.patch.object(cli, "_can_prompt", return_value=True),
            mock.patch("builtins.input", return_value="1"),
            mock.patch.object(cli, "load_registry", return_value=registry),
            mock.patch.object(cli, "find_profiles", side_effect=lambda reg, selector=None: reg["profiles"]),
            mock.patch.object(cli, "run_ssh_config", return_value=subprocess.CompletedProcess(["ssh"], 0, "", "")),
            mock.patch.object(cli, "run_ssh_batch", return_value=subprocess.CompletedProcess(["ssh"], 0, "", "")),
            mock.patch.object(cli, "run_ssh_info", return_value=subprocess.CompletedProcess(["ssh"], 0, "", "")),
            mock.patch.object(cli, "save_registry"),
        ):
            rc, stdout, _ = run_cli(["check"])

        self.assertEqual(rc, 0)
        self.assertIn("no active profile. Select a profile", stdout)
        self.assertIn("OK gpu01.", stdout)

    def test_parse_system_info_skips_no_gpu_message(self) -> None:
        self.assertEqual(
            cli._parse_system_info("memory=125.8GB\ngpu=No devices were found 0.0GB\n"),
            {"memory": "125.8GB"},
        )

    def test_resources_label_skips_cached_no_gpu_message(self) -> None:
        self.assertEqual(
            cli._resources_label({"system_info": {"memory": "125.8GB", "gpu": "No devices were found 0.0GB"}}),
            "RAM 125.8GB",
        )

    def test_active_row_is_colored_when_stdout_is_tty(self) -> None:
        profiles = [{"key": "gpu01", "alias": "gpu01", "host": "10.0.0.1", "last_check_ok": True}]
        with mock.patch.object(cli, "_color_enabled", return_value=True):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                cli._print_profiles_table(profiles, "gpu01")

        self.assertIn("\033[32m", stdout.getvalue())

    def test_connect_uses_exec_helper(self) -> None:
        registry = {
            "active_profile_key": "gpu01",
            "profiles": [{"key": "gpu01", "alias": "gpu", "host": "10.0.0.1"}],
        }
        called: list[str] = []

        with (
            mock.patch.object(cli, "load_registry", return_value=registry),
            mock.patch.object(cli, "find_profiles", return_value=registry["profiles"]),
            mock.patch.object(cli, "exec_ssh", side_effect=lambda alias: called.append(alias)),
        ):
            rc, _, _ = run_cli(["connect", "gpu01"])

        self.assertEqual(rc, 0)
        self.assertEqual(called, ["gpu"])


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        rc = cli.main(argv)
    return rc, stdout.getvalue(), stderr.getvalue()


if __name__ == "__main__":
    unittest.main()
