"""Read only the simple KEY=VALUE format emitted by init_local.py."""
import os
from pathlib import Path

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
