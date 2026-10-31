"""Read only the simple KEY=VALUE format emitted by init_local.py."""
import os
from pathlib import Path


def read_secret(name):
    """Read one server-only secret without copying its value into os.environ."""
    source = os.environ.get(name + '_FILE', '')
    if not source:
        return os.environ.get(name, '')
    try:
        path = Path(source)
        if path.stat().st_size > 4096:
            raise ValueError
        value = path.read_text(encoding='utf-8').strip()
        if not value or '\n' in value or '\r' in value:
            raise ValueError
    except (OSError, UnicodeError, ValueError):
        raise ValueError(name + '_FILE must contain one readable secret value.') from None
    return value

def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("Invalid .env line: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key.replace("_", "").isalnum():
            raise ValueError("Invalid environment key")
        os.environ.setdefault(key, value.strip())
