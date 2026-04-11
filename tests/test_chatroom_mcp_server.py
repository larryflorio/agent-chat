from __future__ import annotations

import importlib.util
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
    result_queue.put(server.send_message("worker", f"hello from {os.getpid()}")["id"])


def test_cursor_updates_are_monotonic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    server.join("alice")
    server.send_message("bob", "one")
    server.send_message("bob", "two")
    server.send_message("bob", "three")

    assert server.set_cursor("alice", 2) == {"name": "alice", "last_read_id": 2}
    assert server.set_cursor("alice", 1) == {"name": "alice", "last_read_id": 2}
    assert server.set_cursor_value("alice", 1) == 2
    assert server.get_cursor("alice") == {"name": "alice", "last_read_id": 2}


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


def test_chatroom_root_override_prevents_cwd_leak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_root = tmp_path / "state"
    cwd_root = tmp_path / "cwd"
    state_root.mkdir()
    cwd_root.mkdir()

    monkeypatch.setenv("CHATROOM_ROOT", str(state_root))
    monkeypatch.chdir(cwd_root)
    server = load_server(state_root)

    server.join("alice")

    assert (state_root / ".chatroom" / "participants.json").exists()
    assert not (cwd_root / ".chatroom").exists()


def test_handoff_and_visibility_filters_still_work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    server.join("alice")
    server.send_message("bob", "broadcast")
    server.send_message("bob", "private", "alice")
    server.send_message("bob", "other", "carol")
    server.write_summary("bob", "global handoff")
    server.write_summary("bob", "alice handoff", "alice")

    visible = server.read_messages(participant="alice")
    handoff = server.get_handoff("alice", recent_limit=10)

    assert [message["id"] for message in visible] == [1, 2]
    assert [message["id"] for message in handoff["recent_messages"]] == [1, 2]
    assert handoff["latest_message_id"] == 3
    assert handoff["cursor"] == 0
    assert handoff["unread_count"] == 2
    assert handoff["latest_summary"]["scope"] == "alice"


def test_mcp_tools_have_docstrings_for_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    for tool_name in (
        "join",
        "leave",
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


def test_leave_removes_participant_and_emits_system_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    server.join("alice")

    assert server.leave("alice") == {"left": True}
    assert server.leave("alice") == {"left": False}
    assert server.list_participants() == []
    messages = server.read_messages()
    assert messages == [
        {
            "id": 1,
            "ts": messages[0]["ts"],
            "from": "system",
            "to": "all",
            "content": "alice left the chatroom",
        }
    ]


@pytest.mark.parametrize("field,args", [
    ("name", ("", "hello", "all")),
    ("content", ("alice", "", "all")),
    ("to", ("alice", "hello", "")),
])
def test_send_message_rejects_blank_required_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, args: tuple[str, str, str]
) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    with pytest.raises(ValueError, match=rf"{field} must not be blank"):
        server.send_message(*args)


def test_cursor_defaults_and_rejects_future_message_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    assert server.get_cursor("alice") == {"name": "alice", "last_read_id": 0}

    server.send_message("bob", "hello")
    with pytest.raises(ValueError, match="cannot exceed the latest message id"):
        server.set_cursor("alice", 2)


def test_read_unread_respects_mark_read_flag_and_visibility(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    server.join("alice")
    server.send_message("bob", "broadcast")
    server.send_message("bob", "private", "alice")
    server.send_message("bob", "other", "carol")

    unread = server.read_unread("alice", mark_read=False)
    assert [message["id"] for message in unread["messages"]] == [1, 2]
    assert unread["last_read_id"] == 0
    assert server.get_cursor("alice") == {"name": "alice", "last_read_id": 0}

    unread = server.read_unread("alice", mark_read=True)
    assert [message["id"] for message in unread["messages"]] == [1, 2]
    assert unread["last_read_id"] == 2
    assert server.get_cursor("alice") == {"name": "alice", "last_read_id": 2}


def test_read_latest_summary_matches_exact_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    server.write_summary("bob", "global one")
    server.write_summary("bob", "alice one", "alice")
    server.write_summary("bob", "global two")

    assert server.read_latest_summary("alice")["content"] == "alice one"
    assert server.read_latest_summary("all")["content"] == "global two"
    assert server.read_latest_summary("carol") is None


def test_list_participants_returns_sorted_records_and_rejoin_updates_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)

    server.join("zoe", "reviewer")
    server.join("alice", "worker")
    updated = server.join("alice", "lead")

    assert [participant["name"] for participant in updated] == ["alice", "zoe"]
    assert updated[0]["role"] == "lead"
    assert server.list_participants() == updated


def test_concurrent_send_message_assigns_unique_sequential_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATROOM_ROOT", str(tmp_path))
    server = load_server(tmp_path)
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
    assert [message["id"] for message in server.read_messages()] == [1, 2, 3]
