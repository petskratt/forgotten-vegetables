from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

from mm.config import Config
from mm.filesafe import safe_id
from mm.posts import is_system_post, merge_posts
from mm.store import atomic_write_text, load_state, migrate_channel_files, read_json, read_jsonl
from mm.users import avatar_color, avatar_initial, letter_source

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer"
FAVICONS = ("favicon-16x16.png", "favicon-32x32.png", "favicon-96x96.png")

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/png" href="favicon-16x16.png" sizes="16x16">
<link rel="icon" type="image/png" href="favicon-32x32.png" sizes="32x32">
<link rel="icon" type="image/png" href="favicon-96x96.png" sizes="96x96">
<title>/*__TITLE__*/</title>
<style>
/*__CSS__*/
</style>
</head>
<body>
<div id="app">
  <header id="global-header">
    <div class="product">
      <svg class="product-icon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path fill="currentColor" d="M5 6.2A2.2 2.2 0 0 1 7.2 4h9.6A2.2 2.2 0 0 1 19 6.2v7.1a2.2 2.2 0 0 1-2.2 2.2H10l-4.2 3.2V6.2Z"/></svg>
      Channels
    </div>
    <form id="search-form" role="search">
      <div class="search-nav">
        <button type="button" id="search-prev" aria-label="Previous match" title="Previous match">←</button>
        <button type="button" id="search-next" aria-label="Next match" title="Next match">→</button>
      </div>
      <label class="search-box">
        <input id="search-input" type="search" placeholder="Search" autocomplete="off" aria-label="Search messages and files">
      </label>
      <div class="scopes" role="group" aria-label="Search scope">
        <button type="button" id="scope-chat" aria-pressed="true">This chat</button>
        <button type="button" id="scope-all" aria-pressed="false">Everything</button>
      </div>
      <span id="search-status"></span>
    </form>
  </header>
  <aside id="sidebar">
    <input id="chat-filter" type="search" placeholder="Filter chats" autocomplete="off" aria-label="Filter chats">
    <nav id="chat-list"></nav>
  </aside>
  <main id="main">
    <header class="channel-header">
      <div class="channel-heading">
        <h1 id="chat-title">Channels</h1>
        <p id="chat-meta">Open a chat, or search everything.</p>
      </div>
      <div class="channel-nav">
        <button type="button" id="jump-start">Start</button>
        <button type="button" id="jump-end">End</button>
      </div>
    </header>
    <div id="results" hidden></div>
    <div id="transcript"></div>
  </main>
</div>
<script>
window.MM = Object.assign({chats: {}, search: null}, /*__BOOT__*/);
</script>
<script>
/*__JS__*/
</script>
</body>
</html>
"""


def js_embed(value) -> str:
    """JSON that is safe inside a classic script tag or a generated .js file."""
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def render_viewer(out: Path, config: Config) -> Path:
    """Rebuild index.html, per-chat script shims, and the archive-wide search index.

    Browsers will not fetch JSON from a file:// page. Each chat is a normal
    script the page inserts when you open it. CSS and the viewer itself are
    inlined so the folder does not depend on a server.
    """
    state = load_state(out / "state.json")
    me = read_json(out / "me.json", {})
    if not isinstance(me, dict):
        me = {}
    users = read_json(out / "users.json", {})
    if not isinstance(users, dict):
        users = {}
    out.mkdir(parents=True, exist_ok=True)
    for name in FAVICONS:
        shutil.copyfile(VIEWER / "favicon" / name, out / name)
    css = (VIEWER / "viewer.css").read_text(encoding="utf-8")
    # Only a literal </script> can close the inline tag. Escaping every "</"
    # also rewrites the regex /</g inside escapeHtml and the page dies on load.
    script = re.sub(
        r"(?i)</script",
        r"<\\/script",
        (VIEWER / "viewer.js").read_text(encoding="utf-8"),
    )

    manifest = []
    search_rows = []
    chats = out / "chats"
    for channel in config.channels:
        migrate_channel_files(out, channel.id)
        loaded = _load_channel(out, channel.id, state)
        if loaded is None:
            continue
        posts, incomplete = loaded
        visible = posts if config.show_system else [post for post in posts if not is_system_post(post)]
        safe_id(channel.id)
        payload = {
            "channel": {
                "id": channel.id,
                "type": channel.type,
                "team": channel.team,
                "name": channel.name,
                "incomplete": incomplete,
            },
            "posts": [_viewer_post(post, users, config.avatar_letter) for post in visible],
        }
        atomic_write_text(chats / f"{channel.id}.js", f"window.MM_LOAD({js_embed(payload)});\n")
        manifest.append(
            {
                "id": channel.id,
                "type": channel.type,
                "team": channel.team,
                "name": channel.name,
                "posts": len(visible),
                "incomplete": incomplete,
                "file": f"chats/{channel.id}.js",
            }
        )
        for post in visible:
            filenames = [item.get("name") or "" for item in (post.get("files") or []) if item.get("name")]
            message = post.get("message") or ""
            if not message and not filenames:
                continue
            row = {
                "c": channel.id,
                "p": post.get("id"),
                "t": post.get("create_at") or 0,
                "u": post.get("display_name") or "",
                "m": message,
            }
            if filenames:
                row["f"] = filenames
            search_rows.append(row)

    search_rows.sort(key=lambda row: row["t"], reverse=True)
    atomic_write_text(out / "search.js", f"window.MM_SEARCH({js_embed(search_rows)});\n")
    boot = js_embed(
        {
            "me": me.get("id") or "",
            "showSystem": config.show_system,
            "avatarLetter": config.avatar_letter,
            "openAt": config.open_at,
            "manifest": manifest,
        }
    )
    page = (
        PAGE.replace("/*__CSS__*/", css)
        .replace("/*__BOOT__*/", boot)
        .replace("/*__JS__*/", script)
        .replace("/*__TITLE__*/", html.escape(config.title, quote=True))
    )
    index = out / "index.html"
    atomic_write_text(index, page)
    print(f"Wrote {index} ({len(manifest)} chats)")
    return index


def _viewer_post(post: dict, users: dict, which: str) -> dict:
    shown = dict(post)
    source = letter_source(post, users)
    shown["initial"] = avatar_initial(source, which)
    shown["color"] = avatar_color(str(post.get("user_id") or source))
    return shown


def _load_channel(out: Path, channel_id: str, state: dict):
    data_path = out / "data" / f"{channel_id}.json"
    jsonl_path = out / "data" / f"{channel_id}.jsonl"
    if not data_path.is_file() and not jsonl_path.is_file():
        return None
    compiled = []
    if data_path.is_file():
        document = read_json(data_path, {})
        compiled = (document or {}).get("posts") or []
    posts = merge_posts(compiled, read_jsonl(jsonl_path))
    entry = (state.get("channels") or {}).get(channel_id) or {}
    incomplete = jsonl_path.is_file() or (bool(entry) and not entry.get("exhausted"))
    return posts, incomplete
