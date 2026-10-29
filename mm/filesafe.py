from __future__ import annotations

import re

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_CHANNEL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def safe_filename(name: str) -> str:
    base = (name or "").replace("\\", "/").split("/")[-1]
    base = _CONTROL.sub("", base).strip(" .")
    if base in ("", ".", ".."):
        return "file"
    if len(base) > 100:
        stem, dot, ext = base.rpartition(".")
        if dot and len(ext) <= 20 and stem:
            base = stem[:80] + "." + ext
        else:
            base = base[:100]
    return base


def safe_id(value: str) -> str:
    if not value or not _CHANNEL_ID.fullmatch(value):
        raise ValueError(f"Unexpected id {value!r}")
    return value


def media_relpath(channel_id: str, file_id: str, name: str) -> str:
    return f"media/{safe_id(channel_id)}/{safe_id(file_id)}/{safe_filename(name)}"


# Older archives stored media/<channel>/<file_id>_<name>. Ids are 26 chars, so the
# first underscore is the separator even when the filename itself contains some.
_PREFIXED_MEDIA = re.compile(r"^media/([a-z0-9]{26})/([a-z0-9]{26})_(.+)$")


def settle_prefixed_media(out, rel: str) -> str:
    """Move a prefixed attachment into media/<channel>/<file_id>/<name>."""
    match = _PREFIXED_MEDIA.fullmatch(rel or "")
    if not match:
        return rel
    channel, file_id, name = match.groups()
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        return rel
    new_rel = f"media/{channel}/{file_id}/{name}"
    root = out.resolve()
    old = (out / rel).resolve()
    new = (out / new_rel).resolve()
    try:
        old.relative_to(root)
        new.relative_to(root)
    except ValueError:
        return rel
    if old.is_file():
        new.parent.mkdir(parents=True, exist_ok=True)
        if not new.exists():
            old.rename(new)
        elif old != new:
            old.unlink()
    return new_rel
