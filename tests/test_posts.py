import datetime
import json

import pytest

from mm.errors import Halt, annotate
from mm.filesafe import media_relpath, safe_filename
from mm.posts import channel_done, is_system_post, merge_posts, parse_since, posts_page_query, select_posts
from mm.store import migrate_channel_files, write_channel_json
from mm.users import (
    avatar_color,
    avatar_initial,
    is_system_admin,
    letter_source,
    people_label,
    person_label,
    post_author,
)


def test_avatar_initial_uses_the_first_or_last_word():
    assert avatar_initial("ee_c3_andres", "first") == "E"
    assert avatar_initial("ee_c3_andres", "last") == "A"
    assert avatar_initial("Andres Elliku", "first") == "A"
    assert avatar_initial("Andres Elliku", "last") == "E"
    assert avatar_initial("Annes Lõbus", "last") == "L"
    assert avatar_initial("Paavo", "first") == "P"
    assert avatar_initial("---", "first") == "?"
    assert avatar_initial("", "last") == "?"
    assert avatar_initial("ßeta", "first") == "ß"


def test_letter_source_prefers_the_username():
    post = {"user_id": "u", "display_name": "Paavo", "props": {}}
    users = {"u": {"username": "ee_cert-ee_paavo"}}
    assert letter_source(post, users) == "ee_cert-ee_paavo"
    assert avatar_initial(letter_source(post, users), "last") == "P"
    assert avatar_initial(letter_source(post, users), "first") == "E"
    overridden = {"user_id": "u", "display_name": "bot", "props": {"override_username": "deploy_bot"}}
    assert letter_source(overridden, users) == "deploy_bot"
    assert letter_source({"display_name": "Mina"}, {}) == "Mina"


def test_avatar_color_stays_in_a_mid_range():
    import re

    seen = set()
    for index in range(80):
        color = avatar_color(f"user-{index}")
        seen.add(color)
        match = re.fullmatch(r"hsl\((\d+), (\d+)%, (\d+)%\)", color)
        assert match, color
        hue, sat, light = (int(match.group(group)) for group in (1, 2, 3))
        assert 0 <= hue < 360
        assert 34 <= sat <= 47
        assert 32 <= light <= 43
    assert len(seen) > 40
    assert avatar_color("same") == avatar_color("same")


def test_system_posts_are_the_system_type_prefix():
    assert is_system_post({"type": "system_join_channel"}) is True
    assert is_system_post({"type": ""}) is False
    assert is_system_post({}) is False


def test_posts_page_query_asks_for_deleted_posts_only_when_allowed():
    assert posts_page_query(100, None, False) == {"per_page": "100"}
    assert posts_page_query(100, "abc", False) == {"per_page": "100", "before": "abc"}
    assert posts_page_query(100, "abc", True) == {
        "per_page": "100",
        "include_deleted": "true",
        "before": "abc",
    }


def test_is_system_admin_matches_the_role_token():
    assert is_system_admin({"roles": "system_user system_admin"}) is True
    assert is_system_admin({"roles": "system_user"}) is False
    assert is_system_admin({"roles": "system_administrator"}) is False
    assert is_system_admin({}) is False


def test_parse_since_date_and_all():
    assert parse_since("all") is None
    assert parse_since("  ") is None
    assert parse_since(None) is None
    assert parse_since("2024-01-01") == 1704067200000
    assert parse_since(datetime.date(2024, 1, 1)) == 1704067200000
    with pytest.raises(ValueError):
        parse_since("yesterday")


def test_select_posts_keeps_a_full_page_and_sets_the_older_cursor():
    order = ["new", "mid", "old"]
    posts = {"new": {"create_at": 30}, "mid": {"create_at": 20}, "old": {"create_at": 10}}
    result = select_posts(order, posts, None, per_page=3)
    assert result.keep_ids == order
    assert result.before == "old"
    assert result.exhausted is False
    assert result.reached_start is False


def test_select_posts_stops_at_the_cutoff_and_keeps_the_boundary():
    order = ["new", "mid", "old"]
    posts = {"new": {"create_at": 300}, "mid": {"create_at": 200}, "old": {"create_at": 100}}
    result = select_posts(order, posts, 200, per_page=3)
    assert result.keep_ids == ["new", "mid"]
    assert result.before == "mid"
    assert result.exhausted is True
    assert result.reached_start is False


def test_select_posts_short_page_is_the_start_of_the_channel():
    posts = {"only": {"create_at": 5}}
    result = select_posts(["only"], posts, None, per_page=100)
    assert result.reached_start is True
    assert result.exhausted is True
    assert result.before == "only"


def test_select_posts_empty_page_and_missing_ids():
    empty = select_posts([], {}, None, per_page=100)
    assert empty.reached_start is True
    assert empty.keep_ids == []

    # A hole in the map is not a 1970 timestamp, so it must not trip the cutoff.
    result = select_posts(["missing", "new"], {"new": {"create_at": 500}}, 100, per_page=100)
    assert result.keep_ids == ["new"]
    assert result.reached_start is True


def test_channel_done_follows_the_cutoff_and_a_finished_walk():
    assert channel_done(None, None) is False
    assert channel_done({"exhausted": False, "reached_start": False, "since_ms": None}, None) is False
    finished = {"exhausted": True, "reached_start": True, "since_ms": None}
    assert channel_done(finished, 0) is True
    cutoff = {"exhausted": True, "reached_start": False, "since_ms": 1000}
    assert channel_done(cutoff, 1000) is True
    assert channel_done(cutoff, 1500) is True
    assert channel_done(cutoff, 500) is False
    assert channel_done(cutoff, None) is False


def test_merge_posts_dedupes_and_sorts():
    older = [{"id": "a", "create_at": 1, "message": "old"}]
    newer = [{"id": "a", "create_at": 1, "message": "new"}, {"id": "b", "create_at": 2, "message": "b"}]
    merged = merge_posts(older, newer)
    assert [post["message"] for post in merged] == ["new", "b"]


def test_safe_filename_strips_paths_and_limits_length():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("..") == "file"
    assert safe_filename("notes.txt") == "notes.txt"
    assert safe_filename(" quarterly notes.txt ") == "quarterly notes.txt"
    long_name = "a" * 120 + ".txt"
    assert len(safe_filename(long_name)) <= 100
    assert safe_filename(long_name).endswith(".txt")
    channel = "c" * 26
    file_id = "f" * 26
    assert media_relpath(channel, file_id, "../../etc/passwd") == f"media/{channel}/{file_id}/passwd"


def test_prefixed_media_moves_into_a_file_subfolder(tmp_path):
    channel = "c" * 26
    file_id = "f" * 26
    name = "CVE-2026-110264_GitLab_update.pdf"
    old_rel = f"media/{channel}/{file_id}_{name}"
    old = tmp_path / old_rel
    old.parent.mkdir(parents=True)
    old.write_bytes(b"pdf")
    write_channel_json(
        tmp_path,
        {"id": channel, "type": "O", "team": "EE", "name": "town"},
        [
            {
                "id": "p" * 26,
                "create_at": 1,
                "message": "hi",
                "files": [{"id": file_id, "name": name, "local_path": old_rel}],
            }
        ],
        incomplete=False,
    )
    migrate_channel_files(tmp_path, channel)
    new_rel = f"media/{channel}/{file_id}/{name}"
    assert (tmp_path / new_rel).read_bytes() == b"pdf"
    assert not old.exists()
    saved = json.loads((tmp_path / "data" / f"{channel}.json").read_text(encoding="utf-8"))
    assert saved["posts"][0]["files"][0]["local_path"] == new_rel
    migrate_channel_files(tmp_path, channel)
    assert (tmp_path / new_rel).read_bytes() == b"pdf"


def test_people_label_skips_you():
    me = "m" * 26
    other = "o" * 26
    users = {
        me: {"username": "me", "first_name": "Mina"},
        other: {"username": "alice", "first_name": "Alice", "last_name": "Ng"},
    }
    assert people_label([me, other], users, me) == "Alice Ng"
    assert person_label({"nickname": "nick"}) == "nick"
    assert post_author({"user_id": other, "props": {"override_username": "bot"}}, users) == "bot"


def test_annotate_mentions_the_channel_once():
    exc = annotate(Halt("HTTP 429, rate limited"), "Example / town-square", 12)
    assert "Example / town-square" in exc.reason
    assert "12 posts saved" in exc.reason
    assert annotate(exc, "other", 1) is exc
