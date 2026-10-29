import subprocess
import sys
from pathlib import Path

from archive import startup_advice

ROOT = Path(__file__).resolve().parents[1]


def test_fresh_checkout_lists_the_setup_commands(tmp_path):
    (tmp_path / ".env.example").write_text("MMHOST=\n", encoding="utf-8")
    text = startup_advice(
        root=tmp_path,
        cwd=tmp_path,
        in_venv=False,
        deps_missing=True,
        env_path=Path(".env"),
    )
    assert text is not None
    commands = [
        line
        for line in text.splitlines()
        if line and not line.startswith("This") and not line.startswith("Fill")
    ]
    assert commands == [
        "python3 -m venv .venv",
        "source .venv/bin/activate",
        "pip install -r requirements.txt",
        "cp .env.example .env",
    ]
    assert text.endswith("run this again.")


def test_active_venv_only_asks_for_the_install(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".env").write_text("MMHOST=https://mm.example\n", encoding="utf-8")
    text = startup_advice(
        root=tmp_path,
        cwd=tmp_path,
        in_venv=True,
        deps_missing=True,
        env_path=Path(".env"),
    )
    assert text is not None
    assert "python3 -m venv" not in text
    assert "source .venv" not in text
    assert "cp .env.example .env" not in text
    assert "pip install -r requirements.txt" in text


def test_missing_env_suggests_the_copy_and_not_a_new_venv(tmp_path):
    (tmp_path / ".env.example").write_text("MMHOST=\n", encoding="utf-8")
    text = startup_advice(
        root=tmp_path,
        cwd=tmp_path,
        in_venv=True,
        deps_missing=False,
        env_path=Path(".env"),
    )
    assert text is not None
    assert text.splitlines() == [
        "No .env yet. Copy the example and fill it in from a logged-in browser session.",
        "",
        "cp .env.example .env",
    ]


def test_running_elsewhere_does_not_offer_to_overwrite_an_existing_env(tmp_path):
    (tmp_path / ".env.example").write_text("MMHOST=\n", encoding="utf-8")
    (tmp_path / ".env").write_text("MMHOST=https://mm.example\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    text = startup_advice(
        root=tmp_path,
        cwd=elsewhere,
        in_venv=True,
        deps_missing=False,
        env_path=Path(".env"),
    )
    assert text is not None
    assert "cp .env.example .env" not in text
    assert f"cd {tmp_path}" in text


def test_a_custom_env_path_is_not_rewritten_as_setup(tmp_path):
    assert (
        startup_advice(
            root=tmp_path,
            cwd=tmp_path,
            in_venv=True,
            deps_missing=False,
            env_path=tmp_path / "secret.env",
        )
        is None
    )


def test_viewer_without_a_chat_list_does_not_ask_for_env(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "archive.py"),
            "viewer",
            "--out",
            str(tmp_path),
            "--env",
            str(tmp_path / "nope"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "cp .env.example" not in result.stderr
    assert "channels.yaml" in result.stderr


def test_missing_custom_env_names_that_file(tmp_path):
    missing = tmp_path / "nope.env"
    result = subprocess.run(
        [sys.executable, str(ROOT / "archive.py"), "--out", str(tmp_path), "--env", str(missing)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "cp .env.example .env" not in result.stderr
    assert f"Env file not found: {missing}" in result.stderr
