from pathlib import Path

from mm.config import load_config, write_discovered
from mm.render import js_embed, render_viewer
from mm.store import write_channel_json, write_json

FAVICON = Path(__file__).resolve().parents[1] / "viewer" / "favicon" / "favicon-32x32.png"


def test_js_embed_neuters_script_breakout():
    text = js_embed({"name": "</script><script>alert(1)</script>"})
    assert "\\u003c/script>" in text
    assert "<script>alert(1)" not in text


def test_viewer_inlines_assets_and_indexes_filenames(tmp_path):
    out = tmp_path / "archive"
    town = "a" * 26
    secret = "b" * 26
    write_discovered(
        out / "channels.yaml",
        [
            {"id": town, "type": "O", "team": "Example", "name": '</script><script>alert(1)</script>'},
            {"id": secret, "type": "P", "team": "Example", "name": "leads"},
        ],
    )
    lines = []
    for line in (out / "channels.yaml").read_text(encoding="utf-8").splitlines():
        if secret in line:
            lines.append("# " + line)
        else:
            lines.append(line)
    (out / "channels.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    write_json(out / "me.json", {"id": "m" * 26, "username": "mina"})
    write_json(
        out / "users.json",
        {"m" * 26: {"id": "m" * 26, "username": "ee_team_quinn", "first_name": "Mina"}},
    )
    write_channel_json(
        out,
        {"id": town, "type": "O", "team": "Example", "name": "town-square"},
        [
            {
                "id": "p" * 26,
                "create_at": 1704067200000,
                "user_id": "m" * 26,
                "message": "the secret pumpkin recipe </script>",
                "root_id": "",
                "type": "",
                "display_name": "Mina",
                "files": [
                    {
                        "id": "f" * 26,
                        "name": "quarterly-notes.txt",
                        "mime_type": "text/plain",
                        "size": 12,
                        "local_path": f"media/{town}/{'f' * 26}_quarterly-notes.txt",
                    }
                ],
            },
            {
                "id": "s" * 26,
                "create_at": 1704067201000,
                "user_id": "m" * 26,
                "message": "Mina joined the channel.",
                "type": "system_join_channel",
                "display_name": "Mina",
                "files": [],
            },
        ],
        incomplete=False,
    )
    # Saved data for a commented-out chat must not show up in the viewer.
    write_channel_json(
        out,
        {"id": secret, "type": "P", "team": "Example", "name": "leads"},
        [{"id": "q" * 26, "create_at": 1, "message": "hidden pumpkin", "display_name": "Ada", "files": []}],
        incomplete=False,
    )

    index = render_viewer(out, load_config(out / "channels.yaml"))
    html = index.read_text(encoding="utf-8")
    assert "<style>" in html and "viewer.css" not in html
    assert "function showChannel" in html or "function renderSidebar" in html
    assert "\\u003c/script>" in html
    assert "<script>alert(1)" not in html
    assert '.replace(/</g, "&lt;")' in html
    assert secret not in html
    assert 'id="global-header"' in html
    assert "hide-system" not in html
    assert "#1e325c" in html
    assert '"showSystem":false' in html
    assert "<title>MM Archive</title>" in html
    assert 'href="favicon-32x32.png"' in html
    assert (out / "favicon-32x32.png").read_bytes() == FAVICON.read_bytes()
    assert 'id="jump-start"' in html and 'id="jump-end"' in html
    assert '"openAt":"end"' in html
    assert 'src="commonmark.js"' in html and 'src="markdown.js"' in html
    assert (out / "commonmark.js").stat().st_size > 100_000
    assert (out / "markdown.js").is_file()
    assert (out / "LICENSE.commonmark.txt").is_file()

    chat_js = (out / "chats" / f"{town}.js").read_text(encoding="utf-8")
    assert chat_js.startswith("window.MM_LOAD(")
    assert "</script>" not in chat_js
    assert '"initial":"Q"' in chat_js
    assert "Mina joined the channel." not in chat_js
    saved = (out / "data" / f"{town}.json").read_text(encoding="utf-8")
    assert f"media/{town}/{'f' * 26}/quarterly-notes.txt" in saved
    assert f"{'f' * 26}_quarterly-notes.txt" not in saved
    search = (out / "search.js").read_text(encoding="utf-8")
    assert "quarterly-notes.txt" in search
    assert "pumpkin" in search
    assert "hidden pumpkin" not in search
    assert "joined the channel" not in search

    text = (out / "channels.yaml").read_text(encoding="utf-8").replace("show_system: false", "show_system: true", 1)
    (out / "channels.yaml").write_text(text, encoding="utf-8")
    render_viewer(out, load_config(out / "channels.yaml"))
    shown = (out / "chats" / f"{town}.js").read_text(encoding="utf-8")
    assert "Mina joined the channel." in shown


def test_tab_title_is_escaped(tmp_path):
    out = tmp_path / "archive"
    write_discovered(out / "channels.yaml", [])
    text = (out / "channels.yaml").read_text(encoding="utf-8")
    text = text.replace('title: "MM Archive"', 'title: "A & B <C>"', 1)
    (out / "channels.yaml").write_text(text, encoding="utf-8")
    index = render_viewer(out, load_config(out / "channels.yaml"))
    html = index.read_text(encoding="utf-8")
    assert "<title>A &amp; B &lt;C&gt;</title>" in html
    assert "<title>A & B" not in html
