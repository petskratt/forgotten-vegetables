import pytest

from mm.config import load_config, write_discovered
from mm.errors import ConfigError
from mm.posts import parse_since


def _chat(suffix: str, kind: str, team: str, name: str) -> dict:
    return {"id": suffix * 26, "type": kind, "team": team, "name": name}


def test_channels_are_one_line_and_comments_survive_a_merge(tmp_path):
    path = tmp_path / "channels.yaml"
    town = _chat("a", "O", "Example", "Town #1: general")
    leads = _chat("b", "P", "Example", "leads")
    alice = _chat("c", "D", "", "Alice, Bob")
    enabled, added = write_discovered(path, [town, leads, alice])
    assert (enabled, added) == (3, 3)

    lines = path.read_text(encoding="utf-8").splitlines()
    channel_lines = [line for line in lines if line.startswith("- {")]
    assert len(channel_lines) == 3
    assert all(line.endswith("}") for line in channel_lines)
    assert 'name: "Town #1: general"' in path.read_text(encoding="utf-8")

    commented = []
    for line in lines:
        if leads["id"] in line:
            commented.append("# " + line)
        else:
            commented.append(line)
    text = "\n".join(commented) + "\n"
    text = text.replace('since: "all"', 'since: "2024-06-01"', 1)
    path.write_text(text, encoding="utf-8")

    fresh = _chat("d", "G", "", "Ada, Lin")
    enabled, added = write_discovered(path, [town, leads, alice, fresh])
    body = path.read_text(encoding="utf-8")
    assert added == 1
    assert enabled == 3
    assert f'# - {{id: "{leads["id"]}"' in body or any(
        line.lstrip().startswith("#") and leads["id"] in line for line in body.splitlines()
    )
    config = load_config(path)
    ids = [channel.id for channel in config.channels]
    assert leads["id"] not in ids
    assert fresh["id"] in ids
    assert town["id"] in ids
    assert config.since_ms == parse_since("2024-06-01")
    assert config.delay_seconds == 0.35
    assert config.show_system is False
    assert config.avatar_letter == "last"
    assert config.title == "MM Archive"
    assert config.open_at == "end"
    assert "show_system: false" in body
    assert 'avatar_letter: "last"' in body
    assert 'title: "MM Archive"' in body
    assert 'open_at: "end"' in body

    enabled_again, added_again = write_discovered(path, [town, leads, alice, fresh])
    assert added_again == 0
    assert enabled_again == 3
    assert path.read_text(encoding="utf-8").count(leads["id"]) == 1


def test_viewer_flags_default_off_and_reject_junk(tmp_path):
    path = tmp_path / "channels.yaml"
    path.write_text('since: "all"\ndelay_seconds: 0.2\nchannels: []\n', encoding="utf-8")
    config = load_config(path)
    assert config.show_system is False
    assert config.avatar_letter == "last"
    assert config.title == "MM Archive"
    assert config.open_at == "end"

    path.write_text(
        'since: "all"\ndelay_seconds: 0.2\nopen_at: start\nchannels: []\n',
        encoding="utf-8",
    )
    assert load_config(path).open_at == "start"

    path.write_text(
        'since: "all"\ndelay_seconds: 0.2\nshow_system: true\navatar_letter: first\nchannels: []\n',
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.show_system is True
    assert config.avatar_letter == "first"

    path.write_text('since: "all"\ndelay_seconds: 0.2\navatar_letter: middle\nchannels: []\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)

    path.write_text('since: "all"\ndelay_seconds: 0.2\nopen_at: middle\nchannels: []\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)

    path.write_text('since: "all"\ndelay_seconds: 0.2\ntitle: 12\nchannels: []\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)

    path.write_text('since: "all"\ndelay_seconds: 0.2\ntitle: "  Soup  "\nchannels: []\n', encoding="utf-8")
    assert load_config(path).title == "Soup"
