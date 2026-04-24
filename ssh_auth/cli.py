from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from typing import Any, Iterable, Sequence

from . import paths
from .codex_config import enable_remote_control


def load_registry() -> Any:
    from .registry import load_registry as impl

    return impl()


def save_registry(registry: Any) -> Any:
    from .registry import save_registry as impl

    return impl(registry)


def upsert_profile(registry: Any, profile: dict[str, Any]) -> Any:
    from .registry import upsert_profile as impl

    return impl(registry, profile)


def remove_profiles(registry: Any, selectors: list[str]) -> Any:
    from .registry import remove_profiles as impl

    return impl(registry, selectors)


def set_active_profile(registry: Any, key: str) -> Any:
    from .registry import set_active_profile as impl

    return impl(registry, key)


def find_profiles(registry: Any, selector: str | None = None) -> list[Any]:
    from .registry import find_profiles as impl

    return list(impl(registry, selector))


def ensure_include() -> Any:
    from .ssh_config import ensure_include as impl

    return impl()


def validate_alias(value: str) -> str:
    from .ssh_config import validate_alias as impl

    return impl(value)


def write_managed_config(registry: Any) -> Any:
    from .ssh_config import write_managed_config as impl

    return impl(_active_key(registry), _iter_profiles(registry))


def run_ssh_config(alias: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-G", alias],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_ssh_batch(alias: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", alias, "true"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_ssh_keygen(identity_file: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-f", os.path.expanduser(identity_file)],
        text=True,
        check=False,
    )


def run_ssh_copy_id(profile: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    target = f"{profile['user']}@{profile['host']}"
    cmd = ["ssh-copy-id"]
    if profile.get("port"):
        cmd.extend(["-p", str(profile["port"])])
    if profile.get("identity_file"):
        cmd.extend(["-i", os.path.expanduser(str(profile["identity_file"])) + ".pub"])
    if profile.get("proxy_jump"):
        cmd.extend(["-o", f"ProxyJump={profile['proxy_jump']}"])
    cmd.append(target)
    return subprocess.run(cmd, text=True, check=False)


def run_ssh_info(alias: str) -> subprocess.CompletedProcess[str]:
    script = (
        "mem=$(awk '/MemTotal/ {printf \"%.1fGB\", $2/1024/1024}' /proc/meminfo 2>/dev/null); "
        "gpu=$(if command -v nvidia-smi >/dev/null 2>&1; then "
        "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>/dev/null | "
        "awk -F, '{gsub(/^ +| +$/, \"\", $1); gsub(/^ +| +$/, \"\", $2); "
        "printf \"%s%s %.1fGB\", sep, $1, $2/1024; sep=\"; \"}'; fi); "
        "printf 'memory=%s\\n' \"$mem\"; printf 'gpu=%s\\n' \"$gpu\""
    )
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", alias, "sh", "-lc", script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def exec_ssh(alias: str) -> None:
    os.execvp("ssh", ["ssh", alias])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ssh-auth")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="initialize ssh-auth files")

    add_parser = subparsers.add_parser("add", help="add or update an SSH profile")
    add_parser.add_argument("key", metavar="profile")
    add_parser.add_argument("--login", help='SSH login command, for example: "ssh ubuntu@1.2.3.4 -p 22"')
    add_parser.add_argument("--host")
    add_parser.add_argument("--user")
    add_parser.add_argument("--port", type=int)
    add_parser.add_argument("--key", "--identity-file", dest="identity_file")
    add_parser.add_argument("--alias")
    add_parser.add_argument("--remote-path")
    add_parser.add_argument("--proxy-jump")
    add_parser.add_argument("--forward-agent", action="store_true")
    add_parser.add_argument("--tag", dest="tags", action="append", default=[])
    add_parser.add_argument("--setup-key", action="store_true", help="copy the public key to the server now")
    add_parser.add_argument("--generate-key", action="store_true", help="generate the SSH key if it does not exist")
    add_parser.add_argument("--no-setup-key", action="store_true", help="do not prompt to set up passwordless login")

    list_parser = subparsers.add_parser("list", help="list SSH profiles")
    list_parser.add_argument("selector", nargs="?")

    subparsers.add_parser("status", help="show active SSH profile")

    switch_parser = subparsers.add_parser("switch", help="switch active SSH profile")
    switch_parser.add_argument("selector")

    remove_parser = subparsers.add_parser("remove", help="remove SSH profiles")
    remove_parser.add_argument("selectors", nargs="+")

    test_parser = subparsers.add_parser("test", help="test SSH profile connectivity")
    test_parser.add_argument("selector", nargs="?")
    test_parser.add_argument("--all", action="store_true", help="test all profiles")

    check_parser = subparsers.add_parser("check", help="check SSH profile connectivity")
    check_parser.add_argument("selector", nargs="?")
    check_parser.add_argument("--all", action="store_true", help="check all profiles")

    connect_parser = subparsers.add_parser("connect", help="exec ssh for a profile")
    connect_parser.add_argument("selector", nargs="?")

    config_parser = subparsers.add_parser("config", help="manage related configuration")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    remote_parser = config_subparsers.add_parser("remote", help="manage Codex remote flag")
    remote_subparsers = remote_parser.add_subparsers(dest="remote_command", required=True)
    remote_subparsers.add_parser("enable", help="enable Codex remote control")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "init":
        return command_init()
    if args.command == "add":
        return command_add(args)
    if args.command == "list":
        return command_list(args)
    if args.command == "status":
        return command_status()
    if args.command == "switch":
        return command_switch(args)
    if args.command == "remove":
        return command_remove(args)
    if args.command == "test":
        return command_check(args)
    if args.command == "check":
        return command_check(args)
    if args.command == "connect":
        return command_connect(args)
    if args.command == "config" and args.config_command == "remote" and args.remote_command == "enable":
        return command_config_remote_enable()
    raise ValueError(f"unknown command: {args.command}")


def command_init() -> int:
    registry = load_registry()
    ensure_include()
    save_registry(registry)
    write_managed_config(registry)
    print("Initialized ssh-auth.")
    return 0


def command_add(args: argparse.Namespace) -> int:
    args = _complete_add_args(args)
    args.key = validate_alias(args.key)
    args.alias = validate_alias(args.alias or args.key)
    _validate_connection_fields(args.host, args.user)
    registry = load_registry()
    profile = {
        "key": args.key,
        "alias": args.alias,
        "host": args.host,
        "user": args.user,
        "port": args.port or 22,
        "identity_file": args.identity_file,
        "remote_path": args.remote_path,
        "proxy_jump": args.proxy_jump,
        "forward_agent": bool(args.forward_agent),
        "tags": args.tags,
    }
    profile = {key: value for key, value in profile.items() if value not in (None, [], "")}
    if _should_setup_key(args):
        profile["_generate_key"] = bool(args.generate_key)
        _setup_passwordless_login(profile)
        profile.pop("_generate_key", None)
    registry = _registry_result_or_original(upsert_profile(registry, profile), registry)
    save_registry(registry)
    ensure_include()
    write_managed_config(registry)
    print(f"Added {args.key}.")
    return 0


def _complete_add_args(args: argparse.Namespace) -> argparse.Namespace:
    if args.login:
        _apply_login_command(args, args.login)

    missing_required = args.host is None or args.user is None
    if not missing_required:
        return args
    if not _can_prompt():
        raise ValueError("add requires --host and --user when stdin is not interactive")

    print(f"Adding SSH profile: {args.key}")
    print("Press Enter to accept defaults. Passwords are not stored by ssh-auth.")
    login = _prompt_optional("SSH login command", None, "for example: ssh ubuntu@1.2.3.4 -p 22")
    if login:
        _apply_login_command(args, login)
        if args.host and args.user:
            print(f"Parsed: {args.user}@{args.host}:{args.port or 22}")

    args.alias = args.alias or _prompt("SSH alias", args.key)
    args.host = _prompt_required("Server host/IP", args.host)
    args.user = _prompt_required("Username", args.user)
    args.port = _prompt_int("Port", args.port or 22)
    default_key = _default_identity_file()
    args.identity_file = args.identity_file or _prompt_optional(
        "Private key path",
        default_key,
        "optional; empty uses SSH defaults, ssh-agent, or password prompt" if default_key is None else "optional",
    )
    args.remote_path = args.remote_path or _prompt_optional("Remote project path", None, "optional")
    args.proxy_jump = args.proxy_jump or _prompt_optional("ProxyJump", None, "optional")
    if not args.forward_agent:
        args.forward_agent = _prompt_yes_no("Forward SSH agent", False)
    if not args.no_setup_key and not args.setup_key:
        args.setup_key = _prompt_yes_no("Set up passwordless login now", True)
    if args.setup_key and not args.generate_key:
        args.generate_key = _prompt_yes_no("Generate SSH key if missing", False)
    return args


def _apply_login_command(args: argparse.Namespace, login: str) -> None:
    parsed = parse_ssh_login_command(login)
    args.host = args.host or parsed.get("host")
    args.user = args.user or parsed.get("user")
    args.port = args.port or parsed.get("port")
    args.identity_file = args.identity_file or parsed.get("identity_file")
    args.proxy_jump = args.proxy_jump or parsed.get("proxy_jump")


def _validate_connection_fields(host: str | None, user: str | None) -> None:
    if not host or host.startswith("-") or any(ch.isspace() for ch in host):
        raise ValueError(f"invalid SSH host: {host!r}")
    if not user or user.startswith("-") or "@" in user or any(ch.isspace() for ch in user):
        raise ValueError(f"invalid SSH username: {user!r}")


def parse_ssh_login_command(login: str) -> dict[str, Any]:
    tokens = shlex.split(login)
    if not tokens:
        raise ValueError("SSH login command is empty")
    if tokens[0] == "ssh":
        tokens = tokens[1:]

    result: dict[str, Any] = {}
    destination: str | None = None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token == "-p":
            i += 1
            if i >= len(tokens):
                raise ValueError("ssh -p requires a port")
            result["port"] = int(tokens[i])
        elif token.startswith("-p") and len(token) > 2:
            result["port"] = int(token[2:])
        elif token in {"-i", "-J"}:
            i += 1
            if i >= len(tokens):
                raise ValueError(f"ssh {token} requires a value")
            if token == "-i":
                result["identity_file"] = tokens[i]
            else:
                result["proxy_jump"] = tokens[i]
        elif token.startswith("-i") and len(token) > 2:
            result["identity_file"] = token[2:]
        elif token.startswith("-J") and len(token) > 2:
            result["proxy_jump"] = token[2:]
        elif token == "-l":
            i += 1
            if i >= len(tokens):
                raise ValueError("ssh -l requires a username")
            result["user"] = tokens[i]
        elif token.startswith("-"):
            pass
        elif destination is None:
            destination = token
        i += 1

    if destination:
        if "@" in destination:
            user, host = destination.rsplit("@", 1)
            result.setdefault("user", user)
            result["host"] = host
        else:
            result["host"] = destination

    return result


def _should_setup_key(args: argparse.Namespace) -> bool:
    return bool(args.setup_key and not args.no_setup_key)


def _setup_passwordless_login(profile: dict[str, Any]) -> None:
    identity_file = str(profile.get("identity_file") or _default_identity_file() or "~/.ssh/id_ed25519")
    profile["identity_file"] = identity_file
    private_path = os.path.expanduser(identity_file)
    public_path = private_path + ".pub"

    if not os.path.exists(private_path):
        generate_key = bool(profile.pop("_generate_key", False))
        if not generate_key:
            raise ValueError(f"private key not found: {private_path}; create it first or pass --generate-key")
        print(f"Generating SSH key: {identity_file}")
        keygen_result = run_ssh_keygen(identity_file)
        if keygen_result.returncode != 0:
            raise ValueError("ssh-keygen failed")
    if not os.path.exists(public_path):
        raise ValueError(f"public key not found: {public_path}")

    print("Copying public key to server. If prompted, enter your SSH password once.")
    copy_result = run_ssh_copy_id(profile)
    if copy_result.returncode != 0:
        raise ValueError("ssh-copy-id failed")


def command_list(args: argparse.Namespace) -> int:
    registry = load_registry()
    profiles = find_profiles(registry, args.selector)
    if not profiles:
        print("No profiles.")
        return 0
    active_key = _active_key(registry)
    _print_profiles_table(profiles, active_key)
    return 0


def command_status() -> int:
    registry = load_registry()
    active_key = _active_key(registry)
    if not active_key:
        print("No active profile.")
        return 1
    matches = _profiles_by_key(registry, active_key)
    if not matches:
        print(f"Active profile missing: {active_key}", file=sys.stderr)
        return 1
    print(f"Active: {_format_profile(matches[0])}")
    return 0


def command_switch(args: argparse.Namespace) -> int:
    registry = load_registry()
    profile = _select_one(registry, args.selector)
    key = _profile_key(profile)
    registry = _registry_result_or_original(set_active_profile(registry, key), registry)
    save_registry(registry)
    write_managed_config(registry)
    print(f"Switched to {key}.")
    return 0


def command_remove(args: argparse.Namespace) -> int:
    registry = load_registry()
    keys = [_profile_key(_select_one(registry, selector)) for selector in args.selectors]
    registry = _registry_result_or_original(remove_profiles(registry, keys), registry)
    save_registry(registry)
    write_managed_config(registry)
    print(f"Removed {', '.join(keys)}.")
    return 0


def command_check(args: argparse.Namespace) -> int:
    registry = load_registry()
    if args.all and args.selector:
        raise ValueError("--all cannot be combined with a profile selector")
    if not args.all and args.selector in {"list", "ls"}:
        _print_profiles_table(find_profiles(registry), _active_key(registry))
        return 0
    profiles = find_profiles(registry) if args.all else [_resolve_profile_for_action(registry, args.selector, "check")]
    if not profiles:
        print("No profiles.")
        return 1

    failures = 0
    for profile in profiles:
        if not _check_one_profile(profile):
            failures += 1
    save_registry(registry)
    return 0 if failures == 0 else 1


def _check_one_profile(profile: Any) -> bool:
    alias = _profile_alias(profile)
    config_result = run_ssh_config(alias)
    if config_result.returncode != 0:
        message = _process_detail(config_result) or "ssh config failed"
        _set_check_result(profile, False, message)
        _print_process_error(f"FAIL {alias}: ssh -G failed", config_result)
        return False

    batch_result = run_ssh_batch(alias)
    if batch_result.returncode != 0:
        message = _process_detail(batch_result) or "connection failed"
        _set_check_result(profile, False, message)
        _print_process_error(f"FAIL {alias}: ssh connection failed", batch_result)
        return False

    info_result = run_ssh_info(alias)
    if info_result.returncode == 0:
        _set_profile_value(profile, "system_info", _parse_system_info(info_result.stdout))
    _set_check_result(profile, True, "OK")
    print(f"OK {alias}.")
    return True


def command_connect(args: argparse.Namespace) -> int:
    registry = load_registry()
    profile = _resolve_profile_for_action(registry, args.selector, "connect")
    exec_ssh(_profile_alias(profile))
    return 0


def command_config_remote_enable() -> int:
    path = enable_remote_control(paths.codex_config_path())
    print(f"Enabled Codex remote control: {path}")
    return 0


def _select_one(registry: Any, selector: str) -> Any:
    profiles = find_profiles(registry)
    row = _profile_by_row(profiles, selector)
    if row is not None:
        return row

    matches = find_profiles(registry, selector)
    if not matches:
        selected = _select_interactively(profiles, f"profile not found: {selector}")
        if selected is not None:
            return selected
        if profiles:
            _print_profiles_table(profiles, _active_key(registry))
            sys.stdout.flush()
        raise ValueError(f"profile not found: {selector}")

    exact = [profile for profile in matches if selector in {_profile_key(profile), _profile_alias(profile)}]
    if len(exact) == 1:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    selected = _select_interactively(matches, f"ambiguous profile {selector}")
    if selected is not None:
        return selected
    _print_profiles_table(matches, _active_key(registry))
    sys.stdout.flush()
    labels = ", ".join(_profile_key(profile) for profile in matches)
    raise ValueError(f"ambiguous profile {selector}: {labels}")


def _resolve_profile_for_action(registry: Any, selector: str | None, action: str) -> Any:
    if selector is not None:
        if selector in {"list", "ls"}:
            profiles = find_profiles(registry)
            _print_profiles_table(profiles, _active_key(registry))
            raise ValueError(f"choose a profile with `ssh-auth {action} <profile-or-number>`")
        return _select_one(registry, selector)

    active_key = _active_key(registry)
    if active_key:
        matches = _profiles_by_key(registry, active_key)
        if matches:
            return matches[0]

    profiles = find_profiles(registry)
    selected = _select_interactively(profiles, "no active profile")
    if selected is not None:
        return selected
    raise ValueError("no active profile")


def _profile_by_row(profiles: list[Any], selector: str) -> Any | None:
    if not selector.isdigit():
        return None
    index = int(selector)
    if 1 <= index <= len(profiles):
        return profiles[index - 1]
    return None


def _select_interactively(profiles: list[Any], reason: str) -> Any | None:
    if not profiles or not _can_prompt():
        return None
    print(f"{reason}. Select a profile:")
    _print_profiles_table(profiles, None)
    while True:
        raw = input("Profile number or name (q to quit): ").strip()
        if raw.casefold() in {"q", "quit", ""}:
            return None
        row = _profile_by_row(profiles, raw)
        if row is not None:
            return row
        exact = [profile for profile in profiles if raw in {_profile_key(profile), _profile_alias(profile)}]
        if len(exact) == 1:
            return exact[0]
        fuzzy = [profile for profile in profiles if raw.casefold() in _profile_key(profile).casefold() or raw.casefold() in _profile_alias(profile).casefold()]
        if len(fuzzy) == 1:
            return fuzzy[0]
        if len(fuzzy) > 1:
            print("Still ambiguous. Enter the row number.", file=sys.stderr)
        else:
            print("No match. Enter a row number or profile name.", file=sys.stderr)


def _can_prompt() -> bool:
    return sys.stdin.isatty()


def _prompt(label: str, default: str | None = None, note: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    note_text = f" ({note})" if note else ""
    value = input(f"{label}{suffix}{note_text}: ").strip()
    return value or (default or "")


def _prompt_required(label: str, current: str | None = None) -> str:
    while True:
        value = _prompt(label, current)
        if value:
            return value
        print(f"{label} is required.", file=sys.stderr)


def _prompt_optional(label: str, default: str | None = None, note: str | None = None) -> str | None:
    value = _prompt(label, default, note)
    return value or None


def _prompt_int(label: str, default: int) -> int:
    while True:
        raw = _prompt(label, str(default))
        try:
            value = int(raw)
        except ValueError:
            print(f"{label} must be a number.", file=sys.stderr)
            continue
        if 1 <= value <= 65535:
            return value
        print(f"{label} must be between 1 and 65535.", file=sys.stderr)


def _prompt_yes_no(label: str, default: bool) -> bool:
    default_label = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{label} [{default_label}]: ").strip().casefold()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Please answer yes or no.", file=sys.stderr)


def _default_identity_file() -> str | None:
    for candidate in ("id_ed25519", "id_rsa", "id_ecdsa"):
        path = paths.ssh_dir() / candidate
        if path.exists():
            return f"~/.ssh/{candidate}"
    return None


def _active_profile(registry: Any) -> Any:
    active_key = _active_key(registry)
    if not active_key:
        raise ValueError("no active profile")
    matches = _profiles_by_key(registry, active_key)
    if not matches:
        raise ValueError(f"active profile missing: {active_key}")
    return matches[0]


def _profiles_by_key(registry: Any, key: str) -> list[Any]:
    matches = find_profiles(registry, key)
    return [profile for profile in matches if _profile_key(profile) == key] or matches


def _active_key(registry: Any) -> str | None:
    value = _get(registry, "active_profile_key")
    if value is None:
        value = _get(registry, "active")
    return str(value) if value else None


def _profile_key(profile: Any) -> str:
    value = _get(profile, "key")
    if value is None:
        raise ValueError("profile is missing key")
    return str(value)


def _profile_alias(profile: Any) -> str:
    return validate_alias(str(_get(profile, "alias") or _profile_key(profile)))


def _format_profile(profile: Any) -> str:
    key = _profile_key(profile)
    alias = _profile_alias(profile)
    host = _get(profile, "host") or _get(profile, "hostname") or "?"
    user = _get(profile, "user")
    port = _get(profile, "port")
    remote_path = _get(profile, "remote_path")

    destination = f"{user}@{host}" if user else str(host)
    if port:
        destination = f"{destination}:{port}"
    label = key if alias == key else f"{key} ({alias})"
    suffix = f" {remote_path}" if remote_path else ""
    return f"{label} -> {destination}{suffix}"


def _print_profiles_table(profiles: list[Any], active_key: str | None) -> None:
    rows = []
    for index, profile in enumerate(profiles, start=1):
        key = _profile_key(profile)
        rows.append(
            {
                "mark": "*" if key == active_key else " ",
                "num": f"{index:02d}",
                "profile": _profile_label(profile),
                "host": _profile_destination(profile),
                "status": _status_label(profile),
                "last_check": _last_check_label(profile),
                "resources": _resources_label(profile),
            }
        )

    columns = [
        ("PROFILE", "profile"),
        ("HOST", "host"),
        ("STATUS", "status"),
        ("LAST CHECK", "last_check"),
        ("RESOURCES", "resources"),
    ]
    widths = {
        key: max(len(title), *(len(row[key]) for row in rows))
        for title, key in columns
    }
    header = "     " + "  ".join(title.ljust(widths[key]) for title, key in columns)
    print(header)
    print("-" * len(header))
    for row in rows:
        prefix = f"{row['mark']} {row['num']} "
        line = prefix + "  ".join(_color_table_cell(row, key, row[key].ljust(widths[key])) for _, key in columns)
        if row["mark"] == "*":
            line = _color(line, "green")
        print(line)
    if active_key is None:
        print("No active profile. Set one with: ssh-auth switch <number-or-profile>")


def _profile_label(profile: Any) -> str:
    key = _profile_key(profile)
    alias = _profile_alias(profile)
    return key if alias == key else f"{key} ({alias})"


def _profile_destination(profile: Any) -> str:
    host = _get(profile, "host") or _get(profile, "hostname") or "?"
    user = _get(profile, "user")
    port = _get(profile, "port")
    destination = f"{user}@{host}" if user else str(host)
    return f"{destination}:{port}" if port else destination


def _status_label(profile: Any) -> str:
    ok = _get(profile, "last_check_ok")
    message = str(_get(profile, "last_check_message") or "")
    if ok is True:
        return "OK"
    if ok is False:
        return _truncate("FAIL" + (f": {message}" if message else ""), 24)
    return "UNKNOWN"


def _color_table_cell(row: dict[str, str], key: str, value: str) -> str:
    if not _color_enabled() or row["mark"] == "*":
        return value
    if key == "status":
        raw = row[key]
        if raw == "OK":
            return _color(value, "green")
        if raw.startswith("FAIL"):
            return _color(value, "red")
        if raw == "UNKNOWN":
            return _color(value, "yellow")
    return value


def _last_check_label(profile: Any) -> str:
    value = _get(profile, "last_check_at")
    try:
        timestamp = int(value or 0)
    except (TypeError, ValueError):
        timestamp = 0
    if timestamp <= 0:
        return "-"

    seconds = max(0, int(time.time()) - timestamp)
    if seconds < 60:
        return "Now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _resources_label(profile: Any) -> str:
    info = _get(profile, "system_info") or {}
    if not isinstance(info, dict):
        return "-"
    parts = []
    gpu = info.get("gpu")
    memory = info.get("memory")
    if gpu and not _gpu_value_is_empty(str(gpu)):
        parts.append(f"GPU {gpu}")
    if memory:
        parts.append(f"RAM {memory}")
    return _truncate("; ".join(parts), 42) if parts else "-"


def _set_check_result(profile: Any, ok: bool, message: str) -> None:
    _set_profile_value(profile, "last_check_at", int(time.time()))
    _set_profile_value(profile, "last_check_ok", ok)
    _set_profile_value(profile, "last_check_message", _truncate(message, 120))


def _parse_system_info(output: str) -> dict[str, str]:
    info: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key == "gpu" and _gpu_value_is_empty(value):
            continue
        if key in {"memory", "gpu"} and value:
            info[key] = value
    return info


def _gpu_value_is_empty(value: str) -> bool:
    normalized = value.strip().casefold()
    return (
        not normalized
        or "no devices were found" in normalized
        or "no devices found" in normalized
        or normalized in {"none", "n/a", "na"}
    )


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 1:
        return value[:limit]
    return value[: limit - 1] + "…"


def _color(value: str, color_name: str) -> str:
    if not _color_enabled():
        return value
    codes = {
        "green": "32",
        "red": "31",
        "yellow": "33",
        "bold": "1",
    }
    code = codes.get(color_name)
    if code is None:
        return value
    return f"\033[{code}m{value}\033[0m"


def _color_enabled() -> bool:
    return (
        sys.stdout.isatty()
        and os.environ.get("NO_COLOR") is None
        and os.environ.get("TERM") != "dumb"
    )


def _get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _set_profile_value(profile: Any, key: str, value: Any) -> None:
    if isinstance(profile, dict):
        profile[key] = value
    else:
        setattr(profile, key, value)


def _registry_result_or_original(result: Any, original: Any) -> Any:
    return result if _looks_like_registry(result) else original


def _looks_like_registry(value: Any) -> bool:
    return value is not None and _get(value, "profiles") is not None


def _print_process_error(prefix: str, result: subprocess.CompletedProcess[str]) -> None:
    detail = _process_detail(result)
    if detail:
        print(f"{prefix}: {detail}", file=sys.stderr)
    else:
        print(prefix, file=sys.stderr)


def _process_detail(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "").strip()


def _iter_profiles(registry: Any) -> Iterable[Any]:
    profiles = _get(registry, "profiles")
    if profiles is None:
        return []
    if isinstance(profiles, dict):
        return profiles.values()
    return profiles


if __name__ == "__main__":
    raise SystemExit(main())
