from __future__ import annotations

import datetime
import re
from dataclasses import dataclass


# Mattermost silently truncates per_page above 200. Stay under that and under
# the default 10 requests/second once delay_seconds is applied.
PER_PAGE_DEFAULT = 100


def posts_page_query(per_page: int, before: str | None, include_deleted: bool) -> dict[str, str]:
    """One newest-first page of channel posts.

    include_deleted is system-admin only. A normal member who sends it gets 403
    before Mattermost checks channel membership. The web client omits it.
    """
    query = {"per_page": str(per_page)}
    if include_deleted:
        query["include_deleted"] = "true"
    if before:
        query["before"] = before
    return query


@dataclass
class PageResult:
    keep_ids: list[str]
    before: str | None
    exhausted: bool
    reached_start: bool


def parse_since(value) -> int | None:
    """UTC millisecond cutoff. None archives the whole channel.

    The posts API `since` parameter is the wrong tool for this: Mattermost
    caps it at 1000 posts and does not promise they are consecutive. Callers
    walk newest-first with `before` and apply this cutoff locally.
    """
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=datetime.timezone.utc)
        return int(value.timestamp() * 1000)
    if isinstance(value, datetime.date):
        moment = datetime.datetime(value.year, value.month, value.day, tzinfo=datetime.timezone.utc)
        return int(moment.timestamp() * 1000)
    text = str(value).strip().lower()
    if text in ("", "all", "none", "~", "null"):
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        moment = datetime.datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
        return int(moment.timestamp() * 1000)
    raise ValueError(f"since must be YYYY-MM-DD or all, got {value!r}")


def select_posts(order: list[str], posts: dict, since_ms: int | None, per_page: int) -> PageResult:
    """Decide which posts on a newest-first page to keep.

    `order` is the Mattermost `order` array. Only those ids are paginated;
    extra posts stuffed into the map (thread context) are ignored so the
    cursor stays honest.
    """
    if not order:
        return PageResult([], None, exhausted=True, reached_start=True)

    keep: list[str] = []
    for post_id in order:
        post = posts.get(post_id)
        if not post:
            continue
        created = post.get("create_at") or 0
        if since_ms is not None and created < since_ms:
            oldest_kept = keep[-1] if keep else None
            return PageResult(keep, oldest_kept, exhausted=True, reached_start=False)
        keep.append(post_id)

    reached_start = len(order) < per_page
    return PageResult(keep, order[-1], exhausted=reached_start, reached_start=reached_start)


def channel_done(entry: dict | None, since_ms: int | None) -> bool:
    """True when this channel does not need another walk for the requested cutoff."""
    if not entry or not entry.get("exhausted"):
        return False
    if entry.get("reached_start"):
        return True
    stored = entry.get("since_ms")
    if since_ms is None:
        return False
    if stored is None:
        return True
    return since_ms >= stored


def merge_posts(*groups: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for group in groups:
        for post in group:
            by_id[post["id"]] = post
    return sorted(by_id.values(), key=lambda post: ((post.get("create_at") or 0), post["id"]))


def is_system_post(post: dict) -> bool:
    return str(post.get("type") or "").startswith("system_")


def blank_entry() -> dict:
    return {
        "before": None,
        "posts_saved": 0,
        "files_done": [],
        "since_ms": None,
        "exhausted": False,
        "reached_start": False,
    }
