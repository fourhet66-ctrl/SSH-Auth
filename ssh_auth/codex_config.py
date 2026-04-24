from __future__ import annotations

from pathlib import Path


def enable_remote_control(path: str | Path) -> Path:
    """Enable Codex remote control in config.toml without a TOML dependency."""
    config_path = Path(path).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        text = config_path.read_text(encoding="utf-8")
    else:
        text = ""

    new_text = _set_remote_control(text)
    config_path.write_text(new_text, encoding="utf-8")
    try:
        config_path.chmod(0o600)
    except OSError:
        pass
    return config_path


def _set_remote_control(text: str) -> str:
    lines = text.splitlines(keepends=True)
    newline = _detect_newline(text)

    features_start = _find_section(lines, "features")
    if features_start is None:
        prefix = "" if not lines or _ends_with_newline(lines[-1]) else newline
        spacer = "" if not lines else newline
        return text + prefix + spacer + "[features]" + newline + "remote_control = true" + newline

    section_end = _find_section_end(lines, features_start + 1)
    remote_idx = _find_key(lines, features_start + 1, section_end, "remote_control")

    if remote_idx is not None:
        lines[remote_idx] = _replace_value(lines[remote_idx], "remote_control = true", newline)
    else:
        insert_at = section_end
        lines.insert(insert_at, "remote_control = true" + newline)

    return "".join(lines)


def _detect_newline(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    return "\n"


def _ends_with_newline(line: str) -> bool:
    return line.endswith("\n") or line.endswith("\r")


def _find_section(lines: list[str], name: str) -> int | None:
    target = f"[{name}]"
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == target:
            return index
    return None


def _find_section_end(lines: list[str], start: int) -> int:
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("[") and stripped.endswith("]") and not stripped.startswith("#"):
            return index
    return len(lines)


def _find_key(lines: list[str], start: int, end: int, key: str) -> int | None:
    for index in range(start, end):
        stripped = lines[index].lstrip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith(key):
            after_key = stripped[len(key) :].lstrip()
            if after_key.startswith("="):
                return index
    return None


def _replace_value(line: str, replacement: str, default_newline: str) -> str:
    newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else default_newline
    leading = line[: len(line) - len(line.lstrip())]
    body = line.rstrip("\r\n")

    comment = ""
    if "#" in body:
        value_part, comment_part = body.split("#", 1)
        if value_part.rstrip().endswith("true") or value_part.rstrip().endswith("false"):
            comment = " #" + comment_part

    return leading + replacement + comment + newline
