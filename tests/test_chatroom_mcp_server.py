from __future__ import annotations

import importlib.util
import json
import multiprocessing
import os
import sys
import types
import uuid
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "chatroom_mcp_server.py"


def install_fake_mcp() -> None:
    if "mcp.server.fastmcp" in sys.modules:
        return

    mcp_module = types.ModuleType("mcp")
    server_module = types.ModuleType("mcp.server")
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")

    class FastMCP:
        def __init__(self, _name: str) -> None:
            self.name = _name

        def tool(self):
            def decorator(func):
                return func

            return decorator

        def run(self, transport: str = "stdio") -> None:
            self.transport = transport

    fastmcp_module.FastMCP = FastMCP
    sys.modules["mcp"] = mcp_module
    sys.modules["mcp.server"] = server_module
    sys.modules["mcp.server.fastmcp"] = fastmcp_module


def load_server(root: Path) -> object:
    install_fake_mcp()
    spec = importlib.util.spec_from_file_location(f"chatroom_server_{uuid.uuid4().hex}", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _concurrent_send_message(root: str, release_queue: multiprocessing.Queue, result_queue: multiprocessing.Queue) -> None:
    os.environ["CHATROOM_ROOT"] = root
    server = load_server(Path(root))
    result_queue.put("ready")
    release_queue.get(timeout=5)
    result_queue.put(server.send_message("worker", "alpha", f"hello from {os.getpid()}")["id"])


def test_topic_lifecycle_status_and_read_only_enforcement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    topic = server.open_topic("parser-refactor", "Parser Refactor")

    assert topic == {
        "id": "parser-refactor",
        "title": "Parser Refactor",
        "status": "open",
        "created_by": "system",
        "created_at": topic["created_at"],
        "closed_at": None,
        "last_activity_ts": topic["last_activity_ts"],
    }
    assert server.close_topic("parser-refactor") == {"closed": True}
    assert server.close_topic("parser-refactor") == {"closed": False}

    closed_topics = server.list_topics(status="closed")
    assert [item["id"] for item in closed_topics] == ["parser-refactor"]
    assert closed_topics[0]["status"] == "closed"
    assert closed_topics[0]["closed_at"] is not None

    with pytest.raises(ValueError, match="is closed"):
        server.send_message("alice", "parser-refactor", "hello")
    with pytest.raises(ValueError, match="is closed"):
        server.write_summary("alice", "parser-refactor", "summary")


def test_duplicate_topic_ids_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    server.open_topic("alpha", "Alpha")

    with pytest.raises(ValueError, match="already exists"):
        server.open_topic("alpha", "Alpha Again")


def test_duplicate_names_are_rejected_across_processes_but_same_process_rejoin_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server_a = load_server(tmp_path)
    server_b = load_server(tmp_path)

    participants = server_a.join("codex", "worker")
    assert participants == [
        {
            "name": "codex",
            "role": "worker",
            "joined_at": participants[0]["joined_at"],
            "last_seen": participants[0]["last_seen"],
        }
    ]

    updated = server_a.join("codex", "reviewer")
    assert updated[0]["role"] == "reviewer"
    assert updated[0]["name"] == "codex"

    with pytest.raises(ValueError, match="already active"):
        server_b.join("codex", "other")


def test_chatroom_root_override_uses_v2_state_and_updates_gitignore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root = tmp_path / "state"
    cwd_root = tmp_path / "cwd"
    state_root.mkdir()
    cwd_root.mkdir()

    monkeypatch.setenv("CHATROOM_ROOT", str(state_root))
    monkeypatch.chdir(cwd_root)
    server = load_server(state_root)

    server.join("alice")

    assert (state_root / ".chatroom_v2" / "participants.json").exists()
    assert not (cwd_root / ".chatroom_v2").exists()
    assert ".chatroom_v2/" in (state_root / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_v2_state_does_not_mutate_existing_v1_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    legacy_dir = tmp_path / ".chatroom"
    legacy_dir.mkdir()
    legacy_participants = legacy_dir / "participants.json"
    legacy_participants.write_text('{"legacy": {"name": "legacy"}}', encoding="utf-8")
    server = load_server(tmp_path)

    server.open_topic("alpha", "Alpha")
    server.send_message("alice", "alpha", "hello")

    assert legacy_participants.read_text(encoding="utf-8") == '{"legacy": {"name": "legacy"}}'
    assert (tmp_path / ".chatroom_v2" / "messages.jsonl").exists()


def test_handoff_visibility_and_summaries_are_topic_scoped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    server.join("alice")
    server.open_topic("alpha", "Alpha")
    server.open_topic("beta", "Beta")
    server.send_message("bob", "alpha", "broadcast")
    server.send_message("bob", "alpha", "private", "alice")
    server.send_message("bob", "alpha", "other", "carol")
    server.send_message("bob", "beta", "beta broadcast")
    server.write_summary("bob", "alpha", "global alpha")
    server.write_summary("bob", "alpha", "alice alpha", "alice")
    server.write_summary("bob", "beta", "global beta")

    visible = server.read_messages("alpha", participant="alice")
    handoff = server.get_handoff("alice", "alpha", recent_limit=10)

    assert [message["id"] for message in visible] == [1, 2]
    assert [message["id"] for message in handoff["recent_messages"]] == [1, 2]
    assert handoff["latest_message_id"] == 3
    assert handoff["cursor"] == 0
    assert handoff["unread_count"] == 2
    assert handoff["latest_summary"]["topic_id"] == "alpha"
    assert handoff["latest_summary"]["scope"] == "alice"
    assert handoff["topic"]["id"] == "alpha"


def test_list_topics_can_include_per_participant_unread_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    server.open_topic("a-first", "A First")
    server.open_topic("z-second", "Z Second")
    server.send_message("bob", "a-first", "broadcast")
    server.send_message("bob", "z-second", "private", "alice")
    server.write_summary("bob", "z-second", "global summary")
    server.read_unread("alice", "a-first", mark_read=True)

    topics = server.list_topics(name="alice", status="all")

    assert [topic["id"] for topic in topics] == ["z-second", "a-first"]
    assert topics[0]["unread_count"] == 1
    assert topics[0]["latest_summary"]["content"] == "global summary"
    assert topics[0]["cursor"] == 0
    assert topics[1]["cursor"] == 1
    assert topics[1]["unread_count"] == 0


def test_cursor_defaults_future_ids_and_topic_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    server.open_topic("alpha", "Alpha")
    server.open_topic("beta", "Beta")
    server.send_message("bob", "alpha", "hello")
    server.send_message("bob", "beta", "world")

    assert server.get_cursor("alice", "alpha") == {"name": "alice", "topic_id": "alpha", "last_read_id": 0}
    assert server.set_cursor("alice", "alpha", 1) == {"name": "alice", "topic_id": "alpha", "last_read_id": 1}
    assert server.set_cursor("alice", "alpha", 0) == {"name": "alice", "topic_id": "alpha", "last_read_id": 1}
    assert server.get_cursor("alice", "beta") == {"name": "alice", "topic_id": "beta", "last_read_id": 0}

    with pytest.raises(ValueError, match="latest message id for this topic"):
        server.set_cursor("alice", "alpha", 2)


def test_read_unread_respects_mark_read_flag_and_topic_boundaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    server.open_topic("alpha", "Alpha")
    server.open_topic("beta", "Beta")
    server.send_message("bob", "alpha", "broadcast")
    server.send_message("bob", "alpha", "private", "alice")
    server.send_message("bob", "alpha", "other", "carol")
    server.send_message("bob", "beta", "beta note")

    unread = server.read_unread("alice", "alpha", mark_read=False)
    assert [message["id"] for message in unread["messages"]] == [1, 2]
    assert unread["last_read_id"] == 0
    assert server.get_cursor("alice", "alpha") == {"name": "alice", "topic_id": "alpha", "last_read_id": 0}

    unread = server.read_unread("alice", "alpha", mark_read=True)
    assert [message["id"] for message in unread["messages"]] == [1, 2]
    assert unread["last_read_id"] == 2
    assert server.get_cursor("alice", "alpha") == {"name": "alice", "topic_id": "alpha", "last_read_id": 2}
    assert server.get_cursor("alice", "beta") == {"name": "alice", "topic_id": "beta", "last_read_id": 0}


def test_read_latest_summary_matches_topic_and_exact_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    server.open_topic("alpha", "Alpha")
    server.open_topic("beta", "Beta")
    server.write_summary("bob", "alpha", "global one")
    server.write_summary("bob", "alpha", "alice one", "alice")
    server.write_summary("bob", "beta", "beta one")
    server.write_summary("bob", "alpha", "global two")

    assert server.read_latest_summary("alpha", "alice")["content"] == "alice one"
    assert server.read_latest_summary("alpha", "all")["content"] == "global two"
    assert server.read_latest_summary("beta", "all")["content"] == "beta one"
    assert server.read_latest_summary("alpha", "carol") is None


def test_get_status_reports_topic_counts_and_last_activity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    server.join("alice")
    server.open_topic("alpha", "Alpha")
    server.open_topic("beta", "Beta")
    server.send_message("bob", "alpha", "hello")
    server.close_topic("beta")

    status = server.get_status()

    assert status["participant_count"] == 1
    assert status["topic_count"] == 2
    assert status["open_topic_count"] == 1
    assert status["message_count"] == 1
    assert status["last_activity_ts"] is not None


@pytest.mark.parametrize(
    "field,args",
    [
        ("name", ("", "alpha", "hello", "all")),
        ("topic_id", ("alice", "", "hello", "all")),
        ("content", ("alice", "alpha", "", "all")),
        ("to", ("alice", "alpha", "hello", "")),
    ],
)
def test_send_message_rejects_blank_required_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    args: tuple[str, str, str, str],
) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)
    server.open_topic("alpha", "Alpha")

    with pytest.raises(ValueError, match=rf"{field} must"):
        server.send_message(*args)


def test_invalid_topic_id_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    with pytest.raises(ValueError, match="topic_id must match"):
        server.open_topic("Bad Topic", "Title")


def test_mcp_tools_have_docstrings_for_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    for tool_name in (
        "join",
        "leave",
        "open_topic",
        "close_topic",
        "list_topics",
        "send_message",
        "read_messages",
        "list_participants",
        "get_status",
        "get_cursor",
        "set_cursor",
        "read_unread",
        "write_summary",
        "read_latest_summary",
        "get_handoff",
    ):
        assert getattr(server, tool_name).__doc__


def test_concurrent_send_message_assigns_unique_sequential_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)
    server.open_topic("alpha", "Alpha")
    ctx = multiprocessing.get_context("fork")
    release_queue = ctx.Queue()
    result_queue = ctx.Queue()
    processes = [
        ctx.Process(target=_concurrent_send_message, args=(str(tmp_path), release_queue, result_queue))
        for _ in range(3)
    ]

    for process in processes:
        process.start()
    for _ in processes:
        assert result_queue.get(timeout=5) == "ready"
    for _ in processes:
        release_queue.put(True)

    ids = sorted(result_queue.get(timeout=5) for _ in processes)

    for process in processes:
        process.join(timeout=5)
        assert process.exitcode == 0

    assert ids == [1, 2, 3]
    assert [message["id"] for message in server.read_messages("alpha")] == [1, 2, 3]


def test_topic_records_persist_as_json_objects(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)
    server.open_topic("alpha", "Alpha")

    topics = json.loads((tmp_path / ".chatroom_v2" / "topics.json").read_text(encoding="utf-8"))

    assert topics["alpha"]["title"] == "Alpha"
