from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_KEYS = (
    "MMAUTHTOKEN",
    "MMUSERID",
    "MMCSRF",
    "MMHOST",
    "USERAGENT",
    "PROXY",
    "SSL_VERIFY",
)


@dataclass
class Settings:
    token: str
    user_id: str
    csrf: str
    host: str
    user_agent: str
    proxy: str
    ssl_verify: str


def parse_env_file(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def load_env(path: Path) -> dict[str, str]:
    file_vals = parse_env_file(path.read_text(encoding="utf-8")) if path.is_file() else {}
    out: dict[str, str] = {}
    for key in ENV_KEYS:
        if file_vals.get(key, "") != "":
            out[key] = file_vals[key]
        elif os.environ.get(key, "") != "":
            out[key] = os.environ[key]
    return out


def settings_from_env(values: dict[str, str]) -> Settings:
    token = values.get("MMAUTHTOKEN", "").strip()
    host = values.get("MMHOST", "").strip()
    if not token:
        raise ValueError("MMAUTHTOKEN is missing from .env")
    if not host:
        raise ValueError("MMHOST is missing from .env")
    return Settings(
        token=token,
        user_id=values.get("MMUSERID", "").strip(),
        csrf=values.get("MMCSRF", "").strip(),
        host=host,
        user_agent=values.get("USERAGENT", "").strip() or "forgotten-vegetables/0.1",
        proxy=values.get("PROXY", "").strip(),
        ssl_verify=values.get("SSL_VERIFY", "").strip(),
    )


def load_settings(path: Path) -> Settings:
    if not path.is_file():
        raise ValueError(f"Env file not found: {path}")
    return settings_from_env(load_env(path))
