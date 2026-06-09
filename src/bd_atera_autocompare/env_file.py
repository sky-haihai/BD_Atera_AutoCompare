from __future__ import annotations

from pathlib import Path


def parse_env_line(line: str) -> tuple[str, str] | None:
    """Parse one .env assignment line while ignoring comments and blanks."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None

    return key, unquote_env_value(value.strip())


def unquote_env_value(value: str) -> str:
    """Remove matching single or double quotes around a .env value."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def load_env_file(path: str | Path) -> dict[str, str]:
    """Load key-value pairs from a local .env file without mutating os.environ."""
    env_path = Path(path)
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    with env_path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            parsed = parse_env_line(line)
            if parsed is None:
                continue
            key, value = parsed
            values[key] = value

    return values
