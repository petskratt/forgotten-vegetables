from __future__ import annotations

import json
import os
from pathlib import Path

from mm.filesafe import settle_prefixed_media
from mm.posts import merge_posts


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    posts = []
    for index, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            posts.append(json.loads(line))
        except json.JSONDecodeError:
            torn = index == len(lines) and not text.endswith("\n")
            if torn:
                continue
            raise
    return posts


def append_jsonl(path: Path, posts: list[dict]) -> None:
    if not posts:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for post in posts:
            handle.write(json.dumps(post, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def migrate_channel_files(out: Path, channel_id: str) -> None:
    """Move prefixed attachment names into a file-id subfolder and remember the new path."""
    data_path = out / "data" / f"{channel_id}.json"
    jsonl_path = out / "data" / f"{channel_id}.jsonl"
    if data_path.is_file():
        document = read_json(data_path, {})
        posts = document.get("posts") if isinstance(document, dict) else None
        if isinstance(posts, list) and _retarget_media(out, posts):
            write_json(data_path, document)
    if jsonl_path.is_file():
        rows = read_jsonl(jsonl_path)
        if _retarget_media(out, rows):
            text = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows)
            atomic_write_text(jsonl_path, text)


def _retarget_media(out: Path, posts: list) -> bool:
    changed = False
    for post in posts:
        if not isinstance(post, dict):
            continue
        for info in post.get("files") or []:
            if not isinstance(info, dict):
                continue
            rel = info.get("local_path") or ""
            new_rel = settle_prefixed_media(out, rel)
            if new_rel != rel:
                info["local_path"] = new_rel
                changed = True
    return changed


def load_saved_posts(out: Path, channel_id: str) -> list[dict]:
    compiled: list[dict] = []
    data_path = out / "data" / f"{channel_id}.json"
    if data_path.is_file():
        document = read_json(data_path, {})
        compiled = document.get("posts") or []
    return merge_posts(compiled, read_jsonl(out / "data" / f"{channel_id}.jsonl"))


def write_channel_json(out: Path, channel: dict, posts: list[dict], incomplete: bool) -> None:
    payload = {
        "channel": {
            "id": channel["id"],
            "type": channel["type"],
            "team": channel.get("team") or "",
            "name": channel.get("name") or "",
        },
        "incomplete": incomplete,
        "posts": posts,
    }
    write_json(out / "data" / f"{channel['id']}.json", payload)


def load_state(path: Path) -> dict:
    state = read_json(path, {})
    if not isinstance(state, dict):
        return {"channels": {}}
    channels = state.get("channels")
    if not isinstance(channels, dict):
        state["channels"] = {}
    return state


def save_state(path: Path, state: dict) -> None:
    channels = {}
    for channel_id, entry in (state.get("channels") or {}).items():
        item = dict(entry)
        item["files_done"] = sorted(set(item.get("files_done") or []))
        channels[channel_id] = item
    payload = {"channels": channels}
    if state.get("me"):
        payload["me"] = state["me"]
    write_json(path, payload)
