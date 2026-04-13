from __future__ import annotations

import argparse
import importlib.util
import json
import uuid
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "chatroom_monitor.py"


def load_monitor() -> object:
    spec = importlib.util.spec_from_file_location(f"chatroom_monitor_{uuid.uuid4().hex}", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def write_messages(path: Path, messages: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(message) + "\n" for message in messages), encoding="utf-8")


def test_load_messages_since_id_returns_all_new_visible_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    monitor = load_monitor()
    write_messages(
        monitor.MESSAGES_PATH,
        [
            {"id": 1, "ts": "2026-04-13T12:00:00Z", "from": "alice", "to": "all", "content": "one"},
            {"id": 2, "ts": "2026-04-13T12:00:01Z", "from": "bob", "to": "alice", "content": "two"},
            {"id": 3, "ts": "2026-04-13T12:00:02Z", "from": "carol", "to": "all", "content": "three"},
            {"id": 4, "ts": "2026-04-13T12:00:03Z", "from": "dave", "to": "alice", "content": "four"},
        ],
    )

    messages, total_count, last_activity_ts, error = monitor.load_messages(limit=1, participant="alice", since_id=1)

    assert error is None
    assert [message["id"] for message in messages] == [2, 3, 4]
    assert total_count == 4
    assert last_activity_ts == "2026-04-13T12:00:03Z"


def test_snapshot_frame_keeps_full_screen_rendering_for_once_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    monitor = load_monitor()
    args = argparse.Namespace(limit=10, interval=2.0, participant="")
    state = {
        "participants": [{"name": "alice", "role": "worker"}],
        "participants_error": None,
        "messages": [{"id": 7, "ts": "2026-04-13T12:00:00Z", "from": "alice", "to": "all", "content": "hello"}],
        "total_count": 7,
        "last_activity_ts": "2026-04-13T12:00:00Z",
        "messages_error": None,
    }

    frame = monitor.snapshot_frame(args, state)

    assert frame.startswith("\x1b[2J\x1b[H")
    assert "Recent messages (showing up to 10):" in frame
    assert "Participants: alice (worker)" in frame


def test_live_status_lines_do_not_emit_screen_clear_sequences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    monitor = load_monitor()
    args = argparse.Namespace(limit=10, interval=2.0, participant="alice")
    state = {
        "participants": [{"name": "alice", "role": "worker"}],
        "participants_error": None,
        "messages_error": None,
        "total_count": 3,
        "last_activity_ts": "2026-04-13T12:00:03Z",
    }

    lines = monitor.live_status_lines(args, state, width=100)

    assert lines
    assert all("\x1b[2J\x1b[H" not in line for line in lines)
    assert any("Participants: alice (worker)" in line for line in lines)


def test_load_cached_state_reuses_cached_results_when_signatures_do_not_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    monitor = load_monitor()
    write_json(monitor.PARTICIPANTS_PATH, {"alice": {"name": "alice", "role": "worker"}})
    write_messages(
        monitor.MESSAGES_PATH,
        [{"id": 1, "ts": "2026-04-13T12:00:00Z", "from": "alice", "to": "all", "content": "hello"}],
    )
    original_load_participants = monitor.load_participants
    original_load_messages = monitor.load_messages
    calls = {"participants": 0, "messages": 0}

    def counted_load_participants():
        calls["participants"] += 1
        return original_load_participants()

    def counted_load_messages(limit: int, participant: str, since_id: int = 0):
        calls["messages"] += 1
        return original_load_messages(limit, participant, since_id)

    monkeypatch.setattr(monitor, "load_participants", counted_load_participants)
    monkeypatch.setattr(monitor, "load_messages", counted_load_messages)
    args = argparse.Namespace(limit=10, interval=2.0, participant="")
    cache = {
        "participants_sig": None,
        "participants": [],
        "participants_error": None,
        "messages_sig": None,
        "messages": [],
        "total_count": 0,
        "last_activity_ts": None,
        "messages_error": None,
    }

    monitor.load_cached_state(args, cache)
    monitor.load_cached_state(args, cache)

    assert calls == {"participants": 1, "messages": 1}
