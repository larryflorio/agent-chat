from __future__ import annotations

import argparse
import importlib.util
import json
import sys
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
        "unread_only": False,
        "latest_topic": False,
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


def seed_overview_filter_state(monitor: object) -> None:
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
            "older-unread": {
                "id": "older-unread",
                "title": "Older Unread",
                "status": "open",
                "created_by": "alice",
                "created_at": "2026-04-13T12:00:00Z",
                "closed_at": None,
                "last_activity_ts": "2026-04-13T12:10:00Z",
            },
            "newer-read": {
                "id": "newer-read",
                "title": "Newer Read",
                "status": "open",
                "created_by": "bob",
                "created_at": "2026-04-13T12:05:00Z",
                "closed_at": None,
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
                "topic_id": "older-unread",
                "from": "alice",
                "to": "all",
                "content": "older one",
            },
            {
                "id": 2,
                "ts": "2026-04-13T12:10:00Z",
                "topic_id": "older-unread",
                "from": "bob",
                "to": "all",
                "content": "older two",
            },
            {
                "id": 3,
                "ts": "2026-04-13T12:05:00Z",
                "topic_id": "newer-read",
                "from": "bob",
                "to": "all",
                "content": "newer one",
            },
            {
                "id": 4,
                "ts": "2026-04-13T12:20:00Z",
                "topic_id": "newer-read",
                "from": "alice",
                "to": "all",
                "content": "newer two",
            },
        ],
    )
    write_json(
        monitor.CURSORS_PATH,
        {
            "alice": {"older-unread": 1, "newer-read": 4},
        },
    )


def seed_latest_topic_state(monitor: object, *, include_closed: bool = True) -> None:
    write_json(
        monitor.PARTICIPANTS_PATH,
        {
            "alice": {"name": "alice", "role": "worker"},
            "bob": {"name": "bob", "role": "reviewer"},
        },
    )
    topics: dict[str, dict[str, object]] = {
        "parser-refactor": {
            "id": "parser-refactor",
            "title": "Parser Refactor",
            "status": "open",
            "created_by": "alice",
            "created_at": "2026-04-13T12:00:00Z",
            "closed_at": None,
            "last_activity_ts": "2026-04-13T12:05:00Z",
        },
        "overview-notes": {
            "id": "overview-notes",
            "title": "Overview Notes",
            "status": "open",
            "created_by": "bob",
            "created_at": "2026-04-13T12:10:00Z",
            "closed_at": None,
            "last_activity_ts": "2026-04-13T12:35:00Z",
        },
        "tie-a": {
            "id": "tie-a",
            "title": "Tie A",
            "status": "open",
            "created_by": "alice",
            "created_at": "2026-04-13T12:20:00Z",
            "closed_at": None,
            "last_activity_ts": "2026-04-13T12:30:00Z",
        },
        "tie-b": {
            "id": "tie-b",
            "title": "Tie B",
            "status": "open",
            "created_by": "bob",
            "created_at": "2026-04-13T12:25:00Z",
            "closed_at": None,
            "last_activity_ts": "2026-04-13T12:30:00Z",
        },
    }
    if include_closed:
        topics["closed-note"] = {
            "id": "closed-note",
            "title": "Closed Note",
            "status": "closed",
            "created_by": "bob",
            "created_at": "2026-04-13T12:40:00Z",
            "closed_at": "2026-04-13T12:40:00Z",
            "last_activity_ts": "2026-04-13T12:40:00Z",
        }
    write_json(monitor.TOPICS_PATH, topics)
    write_messages(
        monitor.MESSAGES_PATH,
        [
            {
                "id": 1,
                "ts": "2026-04-13T12:00:00Z",
                "topic_id": "parser-refactor",
                "from": "alice",
                "to": "all",
                "content": "parser one",
            },
            {
                "id": 2,
                "ts": "2026-04-13T12:05:00Z",
                "topic_id": "parser-refactor",
                "from": "bob",
                "to": "all",
                "content": "parser two",
            },
            {
                "id": 3,
                "ts": "2026-04-13T12:10:00Z",
                "topic_id": "overview-notes",
                "from": "bob",
                "to": "all",
                "content": "overview one",
            },
            {
                "id": 4,
                "ts": "2026-04-13T12:35:00Z",
                "topic_id": "overview-notes",
                "from": "alice",
                "to": "all",
                "content": "overview two",
            },
            {
                "id": 5,
                "ts": "2026-04-13T12:20:00Z",
                "topic_id": "tie-a",
                "from": "alice",
                "to": "all",
                "content": "tie a one",
            },
            {
                "id": 6,
                "ts": "2026-04-13T12:30:00Z",
                "topic_id": "tie-a",
                "from": "bob",
                "to": "all",
                "content": "tie a two",
            },
            {
                "id": 7,
                "ts": "2026-04-13T12:25:00Z",
                "topic_id": "tie-b",
                "from": "bob",
                "to": "all",
                "content": "tie b one",
            },
            {
                "id": 8,
                "ts": "2026-04-13T12:30:00Z",
                "topic_id": "tie-b",
                "from": "alice",
                "to": "all",
                "content": "tie b two",
            },
        ]
        + (
            [
                {
                    "id": 9,
                    "ts": "2026-04-13T12:40:00Z",
                    "topic_id": "closed-note",
                    "from": "bob",
                    "to": "all",
                    "content": "closed one",
                }
            ]
            if include_closed
            else []
        ),
    )
    write_json(
        monitor.CURSORS_PATH,
        {
            "alice": {
                "parser-refactor": 1,
                "overview-notes": 4,
                "tie-a": 4,
                "tie-b": 6,
                "closed-note": 0,
            },
            "bob": {
                "parser-refactor": 2,
                "overview-notes": 4,
                "tie-a": 6,
                "tie-b": 8,
                "closed-note": 9,
            },
        },
    )


@pytest.mark.parametrize(
    ("argv", "message_pattern"),
    [
        (["chatroom_monitor.py", "--unread-only"], r"--unread-only requires --participant"),
        (
            ["chatroom_monitor.py", "--participant", "alice", "--unread-only", "--topic", "older-unread"],
            r"--unread-only is only valid in overview mode",
        ),
        (
            ["chatroom_monitor.py", "--participant", "alice", "--unread-only", "--latest-topic"],
            r"--unread-only is only valid in overview mode",
        ),
        (["chatroom_monitor.py", "--latest-topic"], r"--latest-topic requires --participant"),
        (
            ["chatroom_monitor.py", "--participant", "alice", "--latest-topic", "--topic", "overview-notes"],
            r"--latest-topic cannot be combined with --topic",
        ),
    ],
)
def test_main_rejects_invalid_new_ux_combinations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    message_pattern: str,
) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    monitor = load_monitor()
    monkeypatch.setattr(monitor, "load_cached_state", lambda *args, **kwargs: {})
    monkeypatch.setattr(monitor, "build_view_model", lambda *args, **kwargs: pytest.fail("build_view_model should not run"))
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(ValueError, match=message_pattern):
        monitor.main()


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
    assert "View: overview | Status: open | Participant: alice | Format: text" in frame
    assert "Participants: alice (worker), bob (reviewer)" in frame
    assert "Topics (showing up to 10):" in frame
    assert "[open] parser-refactor" in frame
    assert "unread: 2" in frame
    assert "summary[all]: Parser plan settled" in frame
    assert "Inspect next:" in frame
    assert "python3 chatroom_monitor.py --topic parser-refactor --participant alice" in frame
    assert "python3 chatroom_monitor.py --participant alice --latest-topic" in frame
    assert "monitor-docs" not in frame


def test_overview_unread_only_filters_before_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    monitor = load_monitor()
    seed_overview_filter_state(monitor)
    args = make_args(participant="alice", unread_only=True, limit=1)
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

    assert [topic["id"] for topic in view["topics"]] == ["older-unread"]
    assert "View: overview | Status: open | Participant: alice | Unread only | Format: text" in frame
    assert "[open] older-unread" in frame
    assert "newer-read" not in frame


def test_overview_render_shows_topic_hints_for_participant_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    monitor = load_monitor()
    seed_latest_topic_state(monitor)
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

    assert "python3 chatroom_monitor.py --topic" in frame
    assert "--participant alice" in frame
    assert "python3 chatroom_monitor.py --participant alice --latest-topic" in frame


def test_latest_topic_prefers_latest_unread_and_tie_breaks_by_topic_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    monitor = load_monitor()
    seed_latest_topic_state(monitor)
    args = make_args(participant="alice", latest_topic=True, status="open", limit=2)
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
    payload = json.loads(monitor.render_json_snapshot(args, view))

    assert view["mode"] == "topic"
    assert view["topic"]["id"] == "tie-a"
    assert payload["mode"] == "topic"
    assert payload["topic"]["id"] == "tie-a"
    assert "View: topic tie-a | Participant: alice | Opened via latest-topic | Format: text" in frame
    assert "Topic: tie-a [open]" in frame


def test_latest_topic_falls_back_to_latest_visible_when_unread_counts_are_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    monitor = load_monitor()
    seed_latest_topic_state(monitor)
    args = make_args(participant="bob", latest_topic=True, status="open", limit=2)
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

    assert view["mode"] == "topic"
    assert view["topic"]["id"] == "overview-notes"
    assert view["unread_count"] == 0


def test_latest_topic_respects_status_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    monitor = load_monitor()
    seed_latest_topic_state(monitor)
    args = make_args(participant="alice", latest_topic=True, status="closed", limit=2)
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

    assert view["mode"] == "topic"
    assert view["topic"]["id"] == "closed-note"
    assert view["topic"]["status"] == "closed"


def test_latest_topic_no_match_stays_overview_and_reports_state_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    monitor = load_monitor()
    seed_latest_topic_state(monitor, include_closed=False)
    args = make_args(participant="alice", latest_topic=True, status="closed", limit=2)
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

    assert view["mode"] == "overview"
    assert any("latest-topic" in message and "matching" in message.lower() for message in view["state_messages"])
    assert "latest-topic" in frame
    assert "matching topic" in frame.lower()


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
