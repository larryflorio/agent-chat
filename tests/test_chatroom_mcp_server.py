from __future__ import annotations

import importlib.util
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
