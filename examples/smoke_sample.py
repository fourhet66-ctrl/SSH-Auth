from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        cmd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    print("$ " + " ".join(cmd))
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
    return result


def main() -> int:
    repo = Path(__file__).resolve().parents[1]

    with tempfile.TemporaryDirectory(prefix="ssh-auth-sample-") as temp:
        root = Path(temp)
        home = root / "home"
        codex_home = home / ".codex"
        ssh_dir = home / ".ssh"
        codex_home.mkdir(parents=True)
        ssh_dir.mkdir(parents=True)

        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "CODEX_HOME": str(codex_home),
                "SSH_AUTH_HOME": str(codex_home / "ssh-auth"),
                "SSH_AUTH_SSH_DIR": str(ssh_dir),
                "PYTHONPATH": str(repo),
            }
        )

        run([sys.executable, "-m", "ssh_auth", "init"], env)
        run(
            [
                sys.executable,
                "-m",
                "ssh_auth",
                "add",
                "gpu01",
                "--host",
                "10.0.0.11",
                "--user",
                "ubuntu",
                "--key",
                "~/.ssh/id_ed25519",
                "--remote-path",
                "/home/ubuntu/project-a",
                "--tag",
                "gpu",
            ],
            env,
        )
        run(
            [
                sys.executable,
                "-m",
                "ssh_auth",
                "add",
                "devbox",
                "--host",
                "devbox.example.com",
                "--user",
                "siyuan",
                "--port",
                "2200",
                "--remote-path",
                "/srv/app",
            ],
            env,
        )
        run([sys.executable, "-m", "ssh_auth", "list"], env)
        run([sys.executable, "-m", "ssh_auth", "switch", "gpu01"], env)
        run([sys.executable, "-m", "ssh_auth", "status"], env)
        run([sys.executable, "-m", "ssh_auth", "config", "remote", "enable"], env)

        managed_config = ssh_dir / "config.d" / "codex-ssh-auth.config"
        ssh_config = ssh_dir / "config"
        codex_config = codex_home / "config.toml"

        managed_text = managed_config.read_text(encoding="utf-8")
        ssh_text = ssh_config.read_text(encoding="utf-8")
        codex_text = codex_config.read_text(encoding="utf-8")

        assert "Host gpu01" in managed_text
        assert "Host devbox" in managed_text
        assert "Host codex-active" in managed_text
        assert "HostName 10.0.0.11" in managed_text
        assert "Include ~/.ssh/config.d/*.config" in ssh_text
        assert "remote_control = true" in codex_text

        print("\nGenerated managed SSH config:")
        print(managed_text)
        print("Sample passed.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
