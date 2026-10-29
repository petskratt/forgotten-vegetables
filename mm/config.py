from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML

from mm.errors import ConfigError
from mm.filesafe import safe_id
from mm.posts import parse_since

DEFAULT_DELAY = 0.35
DEFAULT_TITLE = "MM Archive"
CHANNEL_TYPES = ("O", "P", "D", "G")


@dataclass
class Channel:
    id: str
    type: str
    team: str
    name: str

    def label(self) -> str:
        if self.team:
            return f"{self.team} / {self.name}"
        return self.name


@dataclass
class Config:
    since_ms: int | None
    delay_seconds: float
    show_system: bool
    avatar_letter: str
    title: str
    open_at: str
    channels: list[Channel]
    path: Path


def _yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    return yaml


def format_channel_line(channel: dict) -> str:
    team = channel.get("team") or ""
    name = channel.get("name") or ""
    return (
        "- {"
        f"id: {json.dumps(channel['id'], ensure_ascii=False)}, "
        f"type: {json.dumps(channel['type'], ensure_ascii=False)}, "
        f"team: {json.dumps(team, ensure_ascii=False)}, "
        f"name: {json.dumps(name, ensure_ascii=False)}"
        "}"
    )


_ID_IN_FILE = re.compile(r"\bid:\s*\"?([A-Za-z0-9_-]+)")


def load_config(path: Path) -> Config:
    if not path.is_file():
        raise ConfigError(f"Missing {path}. Run: ./archive.py discover")
    try:
        data = _yaml().load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} is empty")
    try:
        since_ms = parse_since(data.get("since", "all"))
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    delay = data.get("delay_seconds", DEFAULT_DELAY)
    try:
        delay_seconds = float(delay)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"delay_seconds must be a number, got {delay!r}") from exc
    if delay_seconds < 0:
        raise ConfigError("delay_seconds cannot be negative")
    show_system = _bool_flag(data, "show_system", False)
    avatar_letter = _avatar_letter(data)
    title = _title(data)
    open_at = _open_at(data)

    channels: list[Channel] = []
    seen: set[str] = set()
    for item in data.get("channels") or []:
        if not isinstance(item, dict):
            raise ConfigError(f"Bad channel entry in {path}")
        channel_id = str(item.get("id") or "").strip()
        kind = str(item.get("type") or "").strip()
        if kind not in CHANNEL_TYPES:
            raise ConfigError(f"Channel {channel_id or item!r} has type {kind!r}, expected one of {CHANNEL_TYPES}")
        try:
            safe_id(channel_id)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        if channel_id in seen:
            continue
        seen.add(channel_id)
        channels.append(
            Channel(
                id=channel_id,
                type=kind,
                team=str(item.get("team") or ""),
                name=str(item.get("name") or channel_id),
            )
        )
    return Config(
        since_ms=since_ms,
        delay_seconds=delay_seconds,
        show_system=show_system,
        avatar_letter=avatar_letter,
        title=title,
        open_at=open_at,
        channels=channels,
        path=path,
    )


def _bool_flag(data: dict, key: str, default: bool) -> bool:
    if key not in data or data.get(key) is None:
        return default
    value = data.get(key)
    if isinstance(value, bool):
        return value
    raise ConfigError(f"{key} must be true or false, got {value!r}")


def _title(data: dict) -> str:
    if "title" not in data or data.get("title") is None:
        return DEFAULT_TITLE
    value = data.get("title")
    if not isinstance(value, str):
        raise ConfigError(f"title must be a string, got {value!r}")
    text = value.strip()
    return text or DEFAULT_TITLE


def _open_at(data: dict) -> str:
    if "open_at" not in data or data.get("open_at") in (None, ""):
        return "end"
    value = str(data.get("open_at")).strip().lower()
    if value not in ("start", "end"):
        raise ConfigError(f"open_at must be start or end, got {data.get('open_at')!r}")
    return value


def _avatar_letter(data: dict) -> str:
    if "avatar_letter" not in data or data.get("avatar_letter") in (None, ""):
        return "last"
    value = str(data.get("avatar_letter")).strip().lower()
    if value not in ("first", "last"):
        raise ConfigError(f"avatar_letter must be first or last, got {data.get('avatar_letter')!r}")
    return value


def write_discovered(path: Path, channels: list[dict]) -> tuple[int, int]:
    """Create channels.yaml, or append chats whose ids are not in the file yet.

    Merge appends lines and does not rewrite the file, so a commented-out chat
    stays commented out and is not added again. Returns (enabled count, newly added).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    added = 0
    if not path.is_file():
        lines = [
            "# UTC date YYYY-MM-DD, or all. Posts older than this are not saved.",
            'since: "all"',
            "# Sleep after every API call, including each file download.",
            f"delay_seconds: {DEFAULT_DELAY}",
            "# Join, leave, and other system posts in the viewer and in search.",
            "show_system: false",
            "# Avatar letter from the username, split on non-letters: first or last word.",
            'avatar_letter: "last"',
            "# Browser tab title.",
            f'title: "{DEFAULT_TITLE}"',
            "# Where a chat opens the first time you view it: start or end.",
            'open_at: "end"',
            "",
            "# Comment out a line to skip that chat. Run discover again to append new chats.",
            "channels:",
        ]
        for channel in channels:
            lines.append(format_channel_line(channel))
            added += 1
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        text = path.read_text(encoding="utf-8")
        present = set(_ID_IN_FILE.findall(text))
        extra = []
        for channel in channels:
            if channel["id"] in present:
                continue
            extra.append(format_channel_line(channel))
            present.add(channel["id"])
            added += 1
        if extra:
            if text and not text.endswith("\n"):
                text += "\n"
            path.write_text(text + "\n".join(extra) + "\n", encoding="utf-8")
    return len(load_config(path).channels), added
