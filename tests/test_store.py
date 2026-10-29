import json

from mm.filesafe import safe_id
from mm.posts import blank_entry, channel_done
from mm.store import load_state, read_jsonl, save_state


def test_torn_last_line_is_skipped_and_a_broken_line_is_not(tmp_path):
    path = tmp_path / "posts.jsonl"
    path.write_text('{"id": "a", "create_at": 1}\n{"id": "b"', encoding="utf-8")
    assert [post["id"] for post in read_jsonl(path)] == ["a"]

    path.write_text('{"id": "a", "create_at": 1}\nnot-json\n', encoding="utf-8")
    try:
        read_jsonl(path)
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("a finished broken line should not be ignored")


def test_state_roundtrip_sorts_file_ids(tmp_path):
    channel_id = safe_id("a" * 26)
    entry = blank_entry()
    entry["files_done"] = {"f" * 26, "e" * 26}
    entry["exhausted"] = True
    entry["since_ms"] = 1000
    path = tmp_path / "state.json"
    save_state(path, {"channels": {channel_id: entry}, "me": {"id": "m" * 26}})
    loaded = load_state(path)
    assert loaded["channels"][channel_id]["files_done"] == ["e" * 26, "f" * 26]
    assert channel_done(loaded["channels"][channel_id], 1000) is True
    assert channel_done(loaded["channels"][channel_id], 100) is False
