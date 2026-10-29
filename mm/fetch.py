from __future__ import annotations

import datetime
from pathlib import Path

from mm.config import Channel, Config
from mm.errors import Halt, annotate
from mm.filesafe import media_relpath
from mm.http import Client
from mm.posts import PER_PAGE_DEFAULT, blank_entry, channel_done, merge_posts, posts_page_query, select_posts
from mm.store import (
    append_jsonl,
    load_saved_posts,
    migrate_channel_files,
    load_state,
    read_json,
    save_state,
    write_channel_json,
    write_json,
)
from mm.users import is_system_admin, post_author, slim_user

PER_PAGE = PER_PAGE_DEFAULT


def fetch(client: Client, out: Path, config: Config) -> None:
    me = client.get_json("/users/me")
    if not isinstance(me, dict) or not me.get("id"):
        raise Halt("Unexpected response from /users/me")
    expected = (client.expected_user_id or "").strip()
    if expected and expected != me.get("id"):
        raise Halt(
            f"MMUSERID is {expected} but the token belongs to {me.get('id')} "
            f"({me.get('username') or 'unknown'})."
        )

    users = read_json(out / "users.json", {})
    if not isinstance(users, dict):
        users = {}
    users[me["id"]] = slim_user(me)
    write_json(out / "users.json", users)
    write_json(out / "me.json", {"id": me["id"], "username": me.get("username") or ""})

    state = load_state(out / "state.json")
    state["me"] = {"id": me["id"], "username": me.get("username") or ""}
    save_state(out / "state.json", state)

    if client.halted:
        raise Halt(
            "Rate limit window is exhausted before any chat was fetched. "
            "Run the same command to continue."
        )

    include_deleted = is_system_admin(me)
    print(
        f"Archiving {len(config.channels)} chats since {format_since(config.since_ms)}, "
        f"delay {config.delay_seconds:g}s"
    )
    for channel in config.channels:
        migrate_channel_files(out, channel.id)
        entry = (state.get("channels") or {}).get(channel.id)
        json_path = out / "data" / f"{channel.id}.json"
        jsonl_path = out / "data" / f"{channel.id}.jsonl"
        if channel_done(entry, config.since_ms) and json_path.is_file() and not jsonl_path.is_file():
            print(f"Skip {channel.label()}, already complete")
            continue
        try:
            _fetch_channel(client, out, channel, state, users, config.since_ms, include_deleted)
        except Halt:
            write_json(out / "users.json", users)
            save_state(out / "state.json", state)
            raise
    write_json(out / "users.json", users)
    save_state(out / "state.json", state)


def format_since(since_ms: int | None) -> str:
    if since_ms is None:
        return "the beginning"
    moment = datetime.datetime.fromtimestamp(since_ms / 1000, datetime.timezone.utc)
    return moment.strftime("%Y-%m-%d")


def _fetch_channel(
    client,
    out: Path,
    channel: Channel,
    state: dict,
    users: dict,
    since_ms: int | None,
    include_deleted: bool,
) -> None:
    label = channel.label()
    print(f"Fetching {label}")
    channels = state.setdefault("channels", {})
    entry = channels.setdefault(channel.id, blank_entry())
    files_done = set(entry.get("files_done") or [])
    entry["files_done"] = files_done
    known = {post["id"]: post for post in load_saved_posts(out, channel.id)}
    meta = {"id": channel.id, "type": channel.type, "team": channel.team, "name": channel.name}
    if channel_done(entry, since_ms) and known:
        _compile(out, meta, known)
        print(f"Finished {label} from posts already saved")
        return
    if channel_done(entry, since_ms):
        entry["exhausted"] = False
        entry["reached_start"] = False

    before = entry.get("before")
    page_no = 0

    while True:
        page_no += 1
        query = posts_page_query(PER_PAGE, before, include_deleted)
        try:
            payload = client.get_json(f"/channels/{channel.id}/posts", query)
        except Halt as exc:
            _remember(entry, known, files_done, since_ms)
            save_state(out / "state.json", state)
            raise annotate(exc, label, len(known)) from exc
        if not isinstance(payload, dict):
            _remember(entry, known, files_done, since_ms)
            save_state(out / "state.json", state)
            raise annotate(Halt("Unexpected posts response"), label, len(known))

        order = payload.get("order") or []
        posts = payload.get("posts") or {}
        result = select_posts(order, posts, since_ms, PER_PAGE)
        fresh = []
        for post_id in result.keep_ids:
            if post_id in known:
                continue
            post = posts.get(post_id)
            if post:
                fresh.append(post)

        try:
            _ensure_users(client, users, [post.get("user_id") for post in fresh], out)
            prepared = [_stored_post(client, channel.id, post, users) for post in fresh]
        except Halt as exc:
            _remember(entry, known, files_done, since_ms)
            save_state(out / "state.json", state)
            raise annotate(exc, label, len(known)) from exc

        if prepared:
            append_jsonl(out / "data" / f"{channel.id}.jsonl", prepared)
            for stored in prepared:
                known[stored["id"]] = stored

        page_posts = [known[post_id] for post_id in result.keep_ids if post_id in known]
        try:
            _download_pending(client, page_posts, files_done, out)
        except Halt as exc:
            _remember(entry, known, files_done, since_ms)
            save_state(out / "state.json", state)
            raise annotate(exc, label, len(known)) from exc

        # A page that is entirely older than `since` has no new cursor. Keep the
        # cursor we requested with, so a later, earlier cutoff can continue.
        if result.before:
            if result.before == before and not result.exhausted:
                _remember(entry, known, files_done, since_ms)
                save_state(out / "state.json", state)
                raise annotate(Halt("Post pagination did not move backward"), label, len(known))
            entry["before"] = result.before
            before = result.before
        entry["exhausted"] = result.exhausted
        entry["reached_start"] = result.reached_start
        entry["since_ms"] = since_ms
        entry["posts_saved"] = len(known)
        entry["files_done"] = files_done
        save_state(out / "state.json", state)
        print(f"  page {page_no}, {len(result.keep_ids)} posts in range")

        if result.exhausted:
            _compile(out, meta, known)
            if client.halted:
                raise annotate(Halt("Rate limit window is exhausted."), label, len(known))
            return
        if client.halted:
            raise annotate(Halt("Rate limit window is exhausted."), label, len(known))


def _compile(out: Path, meta: dict, known: dict) -> None:
    write_channel_json(out, meta, merge_posts(list(known.values())), incomplete=False)
    jsonl = out / "data" / f"{meta['id']}.jsonl"
    if jsonl.exists():
        jsonl.unlink()


def _remember(entry: dict, known: dict, files_done: set, since_ms: int | None) -> None:
    entry["files_done"] = files_done
    entry["posts_saved"] = len(known)
    entry["since_ms"] = since_ms


def _stored_post(client: Client, channel_id: str, post: dict, users: dict) -> dict:
    stored = dict(post)
    stored["display_name"] = post_author(post, users)
    stored["files"] = _file_descriptors(client, channel_id, post)
    return stored


def _file_descriptors(client: Client, channel_id: str, post: dict) -> list[dict]:
    descriptors = []
    for meta in _file_metas(client, post):
        file_id = meta.get("id")
        if not file_id:
            continue
        name = meta.get("name") or "file"
        try:
            rel = media_relpath(channel_id, file_id, name)
        except ValueError as exc:
            raise Halt(str(exc)) from exc
        descriptors.append(
            {
                "id": file_id,
                "name": name,
                "mime_type": meta.get("mime_type") or "",
                "size": meta.get("size"),
                "local_path": rel,
            }
        )
    return descriptors


def _file_metas(client: Client, post: dict) -> list[dict]:
    file_ids = list(post.get("file_ids") or [])
    if not file_ids:
        return []
    meta = ((post.get("metadata") or {}).get("files")) or []
    by_id = {item["id"]: item for item in meta if isinstance(item, dict) and item.get("id")}
    for file_id in file_ids:
        if file_id in by_id:
            continue
        if client.halted:
            raise Halt("Rate limit window is exhausted. Run the same command to continue.")
        info = client.get_json(f"/files/{file_id}/info")
        if isinstance(info, dict) and info.get("id"):
            by_id[info["id"]] = info
    return [by_id[file_id] for file_id in file_ids if file_id in by_id]


def _download_pending(client: Client, posts: list[dict], files_done: set, out: Path) -> None:
    for post in posts:
        for info in post.get("files") or []:
            file_id = info.get("id")
            rel = info.get("local_path")
            if not file_id or not rel:
                continue
            dest = out / rel
            if not _inside(out, dest):
                raise Halt(f"Refusing to write attachment outside the archive: {rel}")
            size = info.get("size")
            if file_id in files_done and _present(dest, size):
                continue
            if _present(dest, size):
                files_done.add(file_id)
                continue
            if client.halted:
                raise Halt("Rate limit window is exhausted. Run the same command to continue.")
            client.download(f"/files/{file_id}", dest)
            files_done.add(file_id)


def _present(path: Path, size) -> bool:
    if not path.is_file():
        return False
    if size is None:
        return True
    try:
        expected = int(size)
    except (TypeError, ValueError):
        return True
    return path.stat().st_size == expected


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _ensure_users(client: Client, users: dict, ids: list, out: Path) -> None:
    missing: list[str] = []
    seen: set[str] = set()
    for user_id in ids:
        if user_id and user_id not in users and user_id not in seen:
            seen.add(user_id)
            missing.append(user_id)
    if not missing:
        return
    for start in range(0, len(missing), 100):
        if client.halted:
            raise Halt("Rate limit window is exhausted. Run the same command to continue.")
        chunk = missing[start : start + 100]
        found = client.post_json("/users/ids", chunk)
        if not isinstance(found, list):
            raise Halt("Unexpected response from /users/ids")
        for user in found:
            if user.get("id"):
                users[user["id"]] = slim_user(user)
        write_json(out / "users.json", users)
