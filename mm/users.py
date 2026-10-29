from __future__ import annotations

import hashlib


def is_system_admin(user: dict) -> bool:
    # Exact role token. Mattermost only allows include_deleted on channel posts
    # when the session user is a system admin, not merely a channel member.
    roles = str(user.get("roles") or "").split()
    return "system_admin" in roles


def avatar_words(name: str) -> list[str]:
    """Pieces of a username split on anything that is not a letter."""
    words: list[str] = []
    current: list[str] = []
    for char in name or "":
        if char.isalpha():
            current.append(char)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return words


def avatar_initial(name: str, which: str = "last") -> str:
    words = avatar_words(name)
    if not words:
        return "?"
    word = words[-1] if which == "last" else words[0]
    letter = word[0]
    upper = letter.upper()
    # ß.upper() is "SS". A circle only has room for one character.
    return upper if len(upper) == 1 else letter


def letter_source(post: dict, users: dict | None) -> str:
    props = post.get("props") or {}
    override = str(props.get("override_username") or "").strip()
    if override:
        return override
    user = (users or {}).get(post.get("user_id") or "") or {}
    username = str(user.get("username") or "").strip()
    if username:
        return username
    return str(post.get("display_name") or "").strip()


def avatar_color(key: str) -> str:
    """Mid saturation, mid lightness. Yellow-green is pulled darker so white type still reads."""
    digest = hashlib.sha256((key or "?").encode("utf-8")).digest()
    hue = int.from_bytes(digest[:2], "big") % 360
    sat = 34 + digest[2] % 14
    if 40 <= hue <= 90:
        light = 32 + digest[3] % 6
    else:
        light = 36 + digest[3] % 8
    return f"hsl({hue}, {sat}%, {light}%)"


def slim_user(user: dict) -> dict:
    return {
        "id": user.get("id") or "",
        "username": user.get("username") or "",
        "first_name": user.get("first_name") or "",
        "last_name": user.get("last_name") or "",
        "nickname": user.get("nickname") or "",
    }


def person_label(user: dict | None) -> str:
    if not user:
        return "unknown"
    first = (user.get("first_name") or "").strip()
    last = (user.get("last_name") or "").strip()
    full = " ".join(part for part in (first, last) if part)
    if full:
        return full
    nick = (user.get("nickname") or "").strip()
    if nick:
        return nick
    username = (user.get("username") or "").strip()
    return username or "unknown"


def post_author(post: dict, users: dict[str, dict]) -> str:
    props = post.get("props") or {}
    override = (props.get("override_username") or "").strip()
    if override:
        return override
    return person_label(users.get(post.get("user_id") or ""))


def people_label(ids: list[str], users: dict[str, dict], me_id: str) -> str:
    others = [person_label(users.get(user_id)) for user_id in ids if user_id and user_id != me_id]
    if not others:
        others = [person_label(users.get(user_id)) for user_id in ids if user_id]
    names = [name for name in others if name and name != "unknown"]
    return ", ".join(names) if names else "unknown"


def dm_user_ids(channel: dict) -> list[str] | None:
    parts = (channel.get("name") or "").split("__")
    if len(parts) == 2 and all(_is_id(part) for part in parts):
        return parts
    return None


def _is_id(value: str) -> bool:
    return len(value) == 26 and value.isalnum() and value.lower() == value
