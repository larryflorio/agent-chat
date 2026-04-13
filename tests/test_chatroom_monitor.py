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


def make_args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "limit": 30,
        "interval": 2.0,
        "participant": "",
        "topic": "",
        "status": "open",
        "format": "text",
        "once": True,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def seed_v2_state(monitor: object) -> None:
    write_json(
        monitor.PARTICIPANTS_PATH,
        {
            "alice": {"name": "alice", "role": "worker"},
            "bob": {"name": "bob", "role": "reviewer"},
        },
    )
    write_json(
        monitor.TOPICS_PATH,
        {
            "parser-refactor": {
                "id": "parser-refactor",
                "title": "Parser Refactor",
                "status": "open",
                "created_by": "alice",
                "created_at": "2026-04-13T12:00:00Z",
                "closed_at": None,
                "last_activity_ts": "2026-04-13T12:10:00Z",
            },
            "monitor-docs": {
                "id": "monitor-docs",
                "title": "Monitor Docs",
                "status": "closed",
                "created_by": "bob",
                "created_at": "2026-04-13T11:45:00Z",
                "closed_at": "2026-04-13T12:20:00Z",
                "last_activity_ts": "2026-04-13T12:20:00Z",
            },
        },
    )
    write_messages(
        monitor.MESSAGES_PATH,
        [
            {
                "id": 1,
                "ts": "2026-04-13T12:00:00Z",
                "topic_id": "parser-refactor",
                "from": "alice",
                "to": "all",
                "content": "kickoff",
            },
            {
                "id": 2,
                "ts": "2026-04-13T12:05:00Z",
                "topic_id": "parser-refactor",
                "from": "bob",
                "to": "alice",
                "content": "private note",
            },
            {
                "id": 3,
                "ts": "2026-04-13T12:10:00Z",
                "topic_id": "parser-refactor",
                "from": "alice",
                "to": "all",
                "content": "followup",
            },
            {
                "id": 4,
                "ts": "2026-04-13T12:20:00Z",
                "topic_id": "monitor-docs",
                "from": "bob",
                "to": "all",
                "content": "docs done",
            },
        ],
    )
    write_messages(
        monitor.SUMMARIES_PATH,
        [
            {
                "id": 1,
                "ts": "2026-04-13T12:09:00Z",
                "topic_id": "parser-refactor",
                "from": "alice",
                "scope": "all",
                "content": "Parser plan settled",
            },
            {
                "id": 2,
                "ts": "2026-04-13T12:21:00Z",
                "topic_id": "monitor-docs",
                "from": "bob",
                "scope": "all",
                "content": "Monitor docs updated",
            },
        ],
    )
    write_json(
        monitor.CURSORS_PATH,
        {
            "alice": {"parser-refactor": 1, "monitor-docs": 0},
            "bob": {"parser-refactor": 2},
        },
    )


def test_load_messages_filters_by_topic_and_participant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    monitor = load_monitor()
    write_messages(
        monitor.MESSAGES_PATH,
        [
            {
                "id": 1,
                "ts": "2026-04-13T12:00:00Z",
                "topic_id": "parser-refactor",
                "from": "alice",
                "to": "all",
                "content": "one",
            },
            {
                "id": 2,
                "ts": "2026-04-13T12:01:00Z",
                "topic_id": "parser-refactor",
                "from": "bob",
                "to": "alice",
                "content": "two",
            },
            {
                "id": 3,
                "ts": "2026-04-13T12:02:00Z",
                "topic_id": "monitor-docs",
                "from": "carol",
                "to": "all",
                "content": "three",
            },
        ],
    )

    messages, total_count, last_activity_ts, error = monitor.load_messages(
        limit=10,
        participant="alice",
        since_id=0,
        topic_id="parser-refactor",
    )

    assert error is None
    assert [message["id"] for message in messages] == [1, 2]
    assert total_count == 3
    assert last_activity_ts == "2026-04-13T12:02:00Z"


def test_overview_render_reports_status_filter_and_unread_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    monitor = load_monitor()
    seed_v2_state(monitor)
    args = make_args(participant="alice", status="open", limit=10)
    state = monitor.load_cached_state(args, {
        "participants_sig": None,
        "topics_sig": None,
        "messages_sig": None,
        "summaries_sig": None,
        "cursors_sig": None,
        "participants": [],
        "participants_error": None,
        "topics": {},
        "topics_error": None,
        "messages": [],
        "messages_error": None,
        "summaries": [],
        "summaries_error": None,
        "cursors": {},
        "cursors_error": None,
    })

    view = monitor.build_view_model(args, state)
    frame = monitor.render_text_snapshot(args, view, width=120)

    assert frame.startswith("\x1b[2J\x1b[H")
    assert "View: overview | Status filter: open | Participant filter: alice | Format: text" in frame
    assert "Participants: alice (worker), bob (reviewer)" in frame
    assert "Topics (showing up to 10):" in frame
    assert "[open] parser-refactor" in frame
    assert "unread: 2" in frame
    assert "summary[all]: Parser plan settled" in frame
    assert "monitor-docs" not in frame


def test_topic_view_json_is_structured_and_participant_filtered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    monitor = load_monitor()
    seed_v2_state(monitor)
    args = make_args(participant="alice", topic="parser-refactor", format="json", status="all", limit=2)
    state = monitor.load_cached_state(args, {
        "participants_sig": None,
        "topics_sig": None,
        "messages_sig": None,
        "summaries_sig": None,
        "cursors_sig": None,
        "participants": [],
        "participants_error": None,
        "topics": {},
        "topics_error": None,
        "messages": [],
        "messages_error": None,
        "summaries": [],
        "summaries_error": None,
        "cursors": {},
        "cursors_error": None,
    })

    view = monitor.build_view_model(args, state)
    payload = json.loads(monitor.render_json_snapshot(args, view))

    assert payload["mode"] == "topic"
    assert payload["topic"]["id"] == "parser-refactor"
    assert payload["topic"]["status"] == "open"
    assert payload["cursor"] == 1
    assert payload["unread_count"] == 2
    assert [message["id"] for message in payload["messages"]] == [2, 3]
    assert payload["latest_summary"]["content"] == "Parser plan settled"
    assert all(message["topic_id"] == "parser-refactor" for message in payload["messages"])


def test_load_cached_state_reuses_cached_results_when_signatures_do_not_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    monitor = load_monitor()
    seed_v2_state(monitor)
    original_load_participants = monitor.load_participants
    original_load_topics = monitor.load_topics
    original_read_message_log = monitor.read_message_log
    original_read_summary_log = monitor.read_summary_log
    original_load_cursors = monitor.load_cursors
    calls = {"participants": 0, "topics": 0, "messages": 0, "summaries": 0, "cursors": 0}

    def counted_load_participants():
        calls["participants"] += 1
        return original_load_participants()

    def counted_load_topics():
        calls["topics"] += 1
        return original_load_topics()

    def counted_read_message_log():
        calls["messages"] += 1
        return original_read_message_log()

    def counted_read_summary_log():
        calls["summaries"] += 1
        return original_read_summary_log()

    def counted_load_cursors():
        calls["cursors"] += 1
        return original_load_cursors()

    monkeypatch.setattr(monitor, "load_participants", counted_load_participants)
    monkeypatch.setattr(monitor, "load_topics", counted_load_topics)
    monkeypatch.setattr(monitor, "read_message_log", counted_read_message_log)
    monkeypatch.setattr(monitor, "read_summary_log", counted_read_summary_log)
    monkeypatch.setattr(monitor, "load_cursors", counted_load_cursors)
    args = make_args()
    cache = {
        "participants_sig": None,
        "topics_sig": None,
        "messages_sig": None,
        "summaries_sig": None,
        "cursors_sig": None,
        "participants": [],
        "participants_error": None,
        "topics": {},
        "topics_error": None,
        "messages": [],
        "messages_error": None,
        "summaries": [],
        "summaries_error": None,
        "cursors": {},
        "cursors_error": None,
    }

    monitor.load_cached_state(args, cache)
    monitor.load_cached_state(args, cache)

    assert calls == {"participants": 1, "topics": 1, "messages": 1, "summaries": 1, "cursors": 1}
