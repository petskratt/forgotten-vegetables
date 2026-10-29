from __future__ import annotations

from pathlib import Path

from mm.config import write_discovered
from mm.errors import Halt
from mm.filesafe import safe_id
from mm.http import Client
from mm.store import read_json, write_json
from mm.users import dm_user_ids, people_label, slim_user


def discover(client: Client, out: Path) -> Path:
    """Write channels.yaml from the teams, channels, DMs, and group chats you belong to.

    Does not download posts. A second run appends chats that were not in the file yet.
    """
    me = _expect_list_or_dict(client.get_json("/users/me"), "user")
    _check_user(client, me)
    users = read_json(out / "users.json", {})
    if not isinstance(users, dict):
        users = {}
    users[me["id"]] = slim_user(me)
    write_json(out / "me.json", {"id": me["id"], "username": me.get("username") or ""})

    teams = client.get_json("/users/me/teams")
    if not isinstance(teams, list):
        raise Halt("Unexpected response from /users/me/teams")
    teams.sort(key=lambda team: (team.get("display_name") or team.get("name") or "").casefold())

    seen: set[str] = set()
    publics: list[tuple[str, dict]] = []
    directs: list[dict] = []
    groups: list[dict] = []

    for team in teams:
        _stop_if_halted(client)
        team_label = team.get("display_name") or team.get("name") or team.get("id") or "team"
        print(f"Team {team_label}")
        channels = client.get_json(
            f"/users/me/teams/{team['id']}/channels",
            {"include_deleted": "false", "last_delete_at": "0"},
        )
        if not isinstance(channels, list):
            raise Halt(f"Unexpected channel list for {team_label}")
        for channel in channels:
            kind = channel.get("type")
            channel_id = channel.get("id")
            if kind not in ("O", "P", "D", "G") or not channel_id or channel_id in seen:
                continue
            try:
                safe_id(channel_id)
            except ValueError as exc:
                raise Halt(str(exc)) from exc
            seen.add(channel_id)
            if kind in ("O", "P"):
                publics.append((team_label, channel))
            elif kind == "D":
                directs.append(channel)
            else:
                groups.append(channel)

    member_ids: dict[str, list[str]] = {}
    for channel in directs:
        parsed = dm_user_ids(channel)
        member_ids[channel["id"]] = parsed if parsed is not None else _members(client, channel["id"])
    for channel in groups:
        member_ids[channel["id"]] = _members(client, channel["id"])

    needed: list[str] = []
    for ids in member_ids.values():
        needed.extend(ids)
    _fetch_users(client, users, needed)
    write_json(out / "users.json", users)

    found: list[dict] = []
    publics.sort(
        key=lambda pair: (
            pair[0].casefold(),
            0 if pair[1].get("type") == "O" else 1,
            _channel_label(pair[1]).casefold(),
        )
    )
    for team_label, channel in publics:
        found.append(
            {
                "id": channel["id"],
                "type": channel["type"],
                "team": team_label,
                "name": _channel_label(channel),
            }
        )
    directs.sort(key=lambda channel: people_label(member_ids.get(channel["id"], []), users, me["id"]).casefold())
    for channel in directs:
        found.append(
            {
                "id": channel["id"],
                "type": "D",
                "team": "",
                "name": people_label(member_ids.get(channel["id"], []), users, me["id"]),
            }
        )
    groups.sort(key=lambda channel: people_label(member_ids.get(channel["id"], []), users, me["id"]).casefold())
    for channel in groups:
        found.append(
            {
                "id": channel["id"],
                "type": "G",
                "team": "",
                "name": people_label(member_ids.get(channel["id"], []), users, me["id"]),
            }
        )

    path = out / "channels.yaml"
    enabled, added = write_discovered(path, found)
    print(f"Wrote {path} ({enabled} chats, {added} newly added).")
    print("Comment out chats you do not want, set since, then run: ./archive.py")
    if client.halted:
        print("The rate limit window was used up as discover finished. Edit the list before running again.")
    return path


def _expect_list_or_dict(value, label: str):
    if not isinstance(value, dict) or not value.get("id"):
        raise Halt(f"Unexpected {label} response")
    return value


def _check_user(client: Client, me: dict) -> None:
    expected = (client.expected_user_id or "").strip()
    if expected and expected != me.get("id"):
        raise Halt(
            f"MMUSERID is {expected} but the token belongs to {me.get('id')} "
            f"({me.get('username') or 'unknown'})."
        )


def _stop_if_halted(client: Client) -> None:
    if client.halted:
        raise Halt("Rate limit window is exhausted during discover. Run the same command to continue.")


def _members(client: Client, channel_id: str) -> list[str]:
    _stop_if_halted(client)
    members = client.get_json(f"/channels/{channel_id}/members", {"page": "0", "per_page": "200"})
    if not isinstance(members, list):
        raise Halt(f"Unexpected member list for channel {channel_id}")
    return [member["user_id"] for member in members if member.get("user_id")]


def _fetch_users(client: Client, users: dict, ids: list[str]) -> None:
    missing: list[str] = []
    seen: set[str] = set()
    for user_id in ids:
        if user_id and user_id not in users and user_id not in seen:
            seen.add(user_id)
            missing.append(user_id)
    for start in range(0, len(missing), 100):
        _stop_if_halted(client)
        chunk = missing[start : start + 100]
        found = client.post_json("/users/ids", chunk)
        if not isinstance(found, list):
            raise Halt("Unexpected response from /users/ids")
        for user in found:
            if user.get("id"):
                users[user["id"]] = slim_user(user)


def _channel_label(channel: dict) -> str:
    return (channel.get("display_name") or channel.get("name") or channel.get("id") or "channel").strip()
