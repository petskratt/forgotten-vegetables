#!/usr/bin/env python3
"""Archive Mattermost chats to JSON, then build a viewer you can open from the folder."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def startup_advice(
    *,
    root: Path,
    cwd: Path,
    in_venv: bool,
    deps_missing: bool,
    env_path: Path,
) -> str | None:
    """Setup commands that are still missing. None when this run is past that."""
    away = cwd.resolve() != root.resolve()
    asked_default = env_path == Path(".env")
    have_project_env = (root / ".env").is_file()
    have_cwd_env = (cwd / ".env").is_file()
    have_example = (root / ".env.example").is_file()

    need_copy = asked_default and not have_project_env and not have_cwd_env and have_example
    need_cd = away and (deps_missing or need_copy or (asked_default and have_project_env and not have_cwd_env))

    commands: list[str] = []
    if need_cd:
        commands.append(f"cd {root}")
    if deps_missing:
        if not in_venv and not (root / ".venv").is_dir():
            commands.append("python3 -m venv .venv")
        if not in_venv:
            commands.append("source .venv/bin/activate")
        commands.append("pip install -r requirements.txt")
    if need_copy:
        commands.append("cp .env.example .env")
    if not commands:
        return None

    if deps_missing:
        lead = "This project is not ready to run yet."
    elif need_cd and not need_copy:
        lead = "Run this from the project directory."
    else:
        lead = "No .env yet. Copy the example and fill it in from a logged-in browser session."

    lines = [lead, "", *commands]
    if deps_missing and need_copy:
        lines.extend(["", "Fill in .env from a logged-in browser session, then run this again."])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 11):
        print("Python 3.11 or newer is required.", file=sys.stderr)
        return 1

    parser = argparse.ArgumentParser(description="Archive Mattermost chats and build a local viewer.")
    parser.add_argument("command", nargs="?", choices=("discover", "fetch", "viewer"))
    parser.add_argument("--env", default=".env", help="env file (default: .env)")
    parser.add_argument("--out", default="archive", help="archive folder (default: archive)")
    args = parser.parse_args(argv)

    try:
        from mm.config import DEFAULT_DELAY, load_config
        from mm.discover import discover
        from mm.env import load_settings
        from mm.errors import ConfigError, Halt
        from mm.fetch import fetch
        from mm.http import Client
        from mm.render import render_viewer
    except ModuleNotFoundError:
        print(
            startup_advice(
                root=ROOT,
                cwd=Path.cwd(),
                in_venv=sys.prefix != sys.base_prefix,
                deps_missing=True,
                env_path=Path(args.env),
            ),
            file=sys.stderr,
        )
        return 1

    out = Path(args.out)
    env_path = Path(args.env)
    yaml_path = out / "channels.yaml"
    command = args.command
    if command is None:
        command = "discover" if not yaml_path.is_file() else "fetch"

    try:
        if command != "viewer" and not env_path.is_file():
            advice = startup_advice(
                root=ROOT,
                cwd=Path.cwd(),
                in_venv=sys.prefix != sys.base_prefix,
                deps_missing=False,
                env_path=env_path,
            )
            if advice:
                print(advice, file=sys.stderr)
            else:
                print(f"Env file not found: {env_path}", file=sys.stderr)
            return 1
        if command == "viewer":
            render_viewer(out, load_config(yaml_path))
            return 0
        if command == "discover":
            settings = load_settings(env_path)
            delay = DEFAULT_DELAY
            if yaml_path.is_file():
                delay = load_config(yaml_path).delay_seconds
            discover(Client(settings, delay), out)
            return 0

        config = load_config(yaml_path)
        client = Client(load_settings(env_path), config.delay_seconds)
        code = 0
        try:
            fetch(client, out, config)
        except Halt as exc:
            print(exc.reason, file=sys.stderr)
            code = 1
        try:
            render_viewer(out, config)
        except Exception as exc:
            print(f"Viewer was not rebuilt: {exc}", file=sys.stderr)
            return 1
        return code
    except Halt as exc:
        print(exc.reason, file=sys.stderr)
        return 1
    except (ConfigError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
