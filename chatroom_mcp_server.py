# Claude Code:
# {
#   "mcpServers": {
#     "chatroom": {
#       "command": "python3",
#       "args": ["chatroom_mcp_server.py"]
#     }
#   }
# }
#
# Codex CLI:
# [mcp_servers.chatroom]
# command = "python3"
# args = ["chatroom_mcp_server.py"]

from __future__ import annotations

import atexit
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import fcntl
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("chatroom")


def resolve_root() -> Path:
    override = os.environ.get("CHATROOM_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent


ROOT = resolve_root()
CHATROOM_DIR = ROOT / ".chatroom"
MESSAGES_PATH = CHATROOM_DIR / "messages.jsonl"
PARTICIPANTS_PATH = CHATROOM_DIR / "participants.json"
CURSORS_PATH = CHATROOM_DIR / "cursors.json"
SUMMARIES_PATH = CHATROOM_DIR / "summaries.jsonl"
GITIGNORE_PATH = ROOT / ".gitignore"
ACTIVE_NAMES: set[str] = set()
MAX_READ_LIMIT = 100


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def strip_text(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    return value.strip()


def require_text(value: str, field: str) -> str:
    value = strip_text(value, field)
    if not value:
        raise ValueError(f"{field} must not be blank")
    return value


def require_window(value: int, field: str) -> int:
    if value < 1 or value > MAX_READ_LIMIT:
        raise ValueError(f"{field} must be between 1 and {MAX_READ_LIMIT}")
    return value


@contextmanager
def locked_file(path: Path, mode: str, lock_type: int) -> Iterator[Any]:
    with path.open(mode, encoding="utf-8") as fp:
        fcntl.flock(fp.fileno(), lock_type)
        try:
            yield fp
        finally:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)


def flush_file(fp: Any) -> None:
    fp.flush()
    os.fsync(fp.fileno())


def ensure_json_file(path: Path) -> None:
    with locked_file(path, "a+", fcntl.LOCK_EX) as fp:
        fp.seek(0)
        if not fp.read():
            fp.seek(0)
            fp.write("{}")
            fp.truncate()
            flush_file(fp)


def ensure_state() -> None:
    CHATROOM_DIR.mkdir(exist_ok=True)
    for path in (MESSAGES_PATH, SUMMARIES_PATH):
        with locked_file(path, "a+", fcntl.LOCK_EX):
            pass
    for path in (PARTICIPANTS_PATH, CURSORS_PATH):
        ensure_json_file(path)
    with locked_file(GITIGNORE_PATH, "a+", fcntl.LOCK_EX) as fp:
        fp.seek(0)
        text = fp.read()
        if ".chatroom/" not in text.splitlines():
            fp.seek(0, os.SEEK_END)
            if text and not text.endswith("\n"):
                fp.write("\n")
            fp.write(".chatroom/\n")
            flush_file(fp)


def load_json_map(path: Path, label: str) -> dict[str, Any]:
    with locked_file(path, "r", fcntl.LOCK_SH) as fp:
        data = json.loads(fp.read() or "{}")
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return data


def update_json_map(path: Path, label: str, updater) -> Any:
    with locked_file(path, "r+", fcntl.LOCK_EX) as fp:
        data = json.loads(fp.read() or "{}")
        if not isinstance(data, dict):
            raise ValueError(f"{label} must contain a JSON object")
        result = updater(data)
        fp.seek(0)
        fp.write(json.dumps(data, ensure_ascii=False, sort_keys=True))
        fp.truncate()
        flush_file(fp)
        return result


def append_jsonl(path: Path, payload: dict[str, Any]) -> int:
    with locked_file(path, "a+", fcntl.LOCK_EX) as fp:
        fp.seek(0)
        record_id = sum(1 for _ in fp) + 1
        record = {"id": record_id, **payload}
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        flush_file(fp)
    return record_id


def sort_participants(data: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    return [data[name] for name in sorted(data)]


def scan_messages(participant: str = "") -> tuple[list[dict[str, Any]], int]:
    visible: list[dict[str, Any]] = []
    latest_id = 0
    with locked_file(MESSAGES_PATH, "r", fcntl.LOCK_SH) as fp:
        for line in fp:
            if not line.strip():
                continue
            message = json.loads(line)
            latest_id = message["id"]
            if participant and message["to"] not in {"all", participant}:
                continue
            visible.append(
                {
                    "id": message["id"],
                    "ts": message["ts"],
                    "from": message["from"],
                    "to": message["to"],
                    "content": message["content"],
                }
            )
    return visible, latest_id


def latest_summary(scope: str = "", include_global: bool = False) -> dict[str, Any] | None:
    target = {scope} if scope else {"all"}
    if include_global and scope:
        target.add("all")
    found = None
    with locked_file(SUMMARIES_PATH, "r", fcntl.LOCK_SH) as fp:
        for line in fp:
            if not line.strip():
                continue
            summary = json.loads(line)
            if summary["scope"] in target:
                found = summary
    return found


def get_cursor_value(name: str) -> int:
    value = load_json_map(CURSORS_PATH, "cursors.json").get(name, 0)
    if not isinstance(value, int) or value < 0:
        raise ValueError("cursors.json must contain non-negative integer values")
    return value


def set_cursor_value(name: str, message_id: int) -> int:
    return update_json_map(
        CURSORS_PATH,
        "cursors.json",
        lambda data: (
            data.__setitem__(name, max(message_id, int(data.get(name, 0) or 0)))
            or data[name]
        ),
    )


def leave_internal(name: str) -> bool:
    ensure_state()
    removed = update_json_map(
        PARTICIPANTS_PATH,
        "participants.json",
        lambda data: bool(data.pop(name, None)),
    )
    ACTIVE_NAMES.discard(name)
    if removed:
        append_jsonl(
            MESSAGES_PATH,
            {"ts": utc_now(), "from": "system", "to": "all", "content": f"{name} left the chatroom"},
        )
    return removed


def cleanup() -> None:
    for name in list(ACTIVE_NAMES):
        try:
            leave_internal(name)
        except Exception:
            pass


atexit.register(cleanup)


@mcp.tool()
def join(name: str, role: str = "general") -> list[dict[str, str]]:
    """Register this agent as active in the shared chatroom."""
    name = require_text(name, "name")
    role = strip_text(role, "role")
    ensure_state()
    now = utc_now()
    def update_participants(data: dict[str, dict[str, str]]) -> list[dict[str, str]]:
        existing = data.get(name)
        if existing and name not in ACTIVE_NAMES:
            raise ValueError(f"participant {name!r} is already active; choose a different name or remove the stale participant")
        data[name] = {
            "name": name,
            "role": role,
            "joined_at": (existing or {}).get("joined_at", now),
            "last_seen": now,
        }
        return sort_participants(data)

    participants = update_json_map(PARTICIPANTS_PATH, "participants.json", update_participants)
    ACTIVE_NAMES.add(name)
    return participants


@mcp.tool()
def leave(name: str) -> dict[str, bool]:
    """Remove this agent from active participants and emit a system leave message."""
    return {"left": leave_internal(require_text(name, "name"))}


@mcp.tool()
def send_message(name: str, content: str, to: str = "all") -> dict[str, int]:
    """Append a broadcast or directed message to the shared message log."""
    ensure_state()
    return {
        "id": append_jsonl(
            MESSAGES_PATH,
            {
                "ts": utc_now(),
                "from": require_text(name, "name"),
                "to": require_text(to, "to"),
                "content": require_text(content, "content"),
            },
        )
    }


@mcp.tool()
def read_messages(since_id: int = 0, limit: int = 50, participant: str = "") -> list[dict[str, Any]]:
    """Read recent messages after a given id, optionally filtered by recipient visibility."""
    if since_id < 0:
        raise ValueError("since_id must be >= 0")
    ensure_state()
    participant = strip_text(participant, "participant")
    limit = require_window(limit, "limit")
    visible, _ = scan_messages(participant)
    return [message for message in visible if message["id"] > since_id][:limit]


@mcp.tool()
def list_participants() -> list[dict[str, str]]:
    """List active chatroom participants sorted by name."""
    ensure_state()
    return sort_participants(load_json_map(PARTICIPANTS_PATH, "participants.json"))


@mcp.tool()
def get_status() -> dict[str, Any]:
    """Return aggregate participant and message status for the chatroom."""
    ensure_state()
    participant_count = len(load_json_map(PARTICIPANTS_PATH, "participants.json"))
    _, latest_id = scan_messages()
    last_activity_ts = None
    message_count = latest_id
    if latest_id:
        with locked_file(MESSAGES_PATH, "r", fcntl.LOCK_SH) as fp:
            for line in fp:
                if line.strip():
                    last_activity_ts = json.loads(line)["ts"]
    return {
        "participant_count": participant_count,
        "message_count": message_count,
        "last_activity_ts": last_activity_ts,
    }


@mcp.tool()
def get_cursor(name: str) -> dict[str, int | str]:
    """Return the stored unread cursor for a participant."""
    ensure_state()
    name = require_text(name, "name")
    return {"name": name, "last_read_id": get_cursor_value(name)}


@mcp.tool()
def set_cursor(name: str, message_id: int) -> dict[str, int | str]:
    """Advance a participant cursor to a specific message id without allowing regression."""
    ensure_state()
    name = require_text(name, "name")
    if message_id < 0:
        raise ValueError("message_id must be >= 0")
    _, latest_id = scan_messages()
    if message_id > latest_id:
        raise ValueError("message_id cannot exceed the latest message id")
    return {"name": name, "last_read_id": set_cursor_value(name, message_id)}


@mcp.tool()
def read_unread(name: str, limit: int = 50, mark_read: bool = True) -> dict[str, Any]:
    """Read messages after this participant's cursor and optionally advance it."""
    ensure_state()
    name = require_text(name, "name")
    limit = require_window(limit, "limit")
    cursor = get_cursor_value(name)
    visible, _ = scan_messages(name)
    messages = [message for message in visible if message["id"] > cursor][:limit]
    if mark_read and messages:
        cursor = set_cursor_value(name, messages[-1]["id"])
    return {"name": name, "last_read_id": cursor, "messages": messages}


@mcp.tool()
def write_summary(name: str, content: str, scope: str = "all") -> dict[str, int]:
    """Persist a summary record for cross-session handoff."""
    ensure_state()
    return {
        "id": append_jsonl(
            SUMMARIES_PATH,
            {
                "ts": utc_now(),
                "from": require_text(name, "name"),
                "scope": require_text(scope, "scope"),
                "content": require_text(content, "content"),
            },
        )
    }


@mcp.tool()
def read_latest_summary(scope: str = "all") -> dict[str, Any] | None:
    """Return the latest summary whose scope exactly matches the requested scope."""
    ensure_state()
    return latest_summary(require_text(scope, "scope"))


@mcp.tool()
def get_handoff(name: str = "", recent_limit: int = 10) -> dict[str, Any]:
    """Return a compact orientation payload for a new or resumed agent session."""
    ensure_state()
    name = strip_text(name, "name")
    recent_limit = require_window(recent_limit, "recent_limit")
    participants = sort_participants(load_json_map(PARTICIPANTS_PATH, "participants.json"))
    visible, latest_id = scan_messages(name)
    cursor = get_cursor_value(name) if name else None
    unread_count = len([message for message in visible if name and message["id"] > cursor]) if name else None
    recent_messages = visible[-recent_limit:]
    return {
        "participants": participants,
        "latest_message_id": latest_id,
        "cursor": cursor,
        "unread_count": unread_count,
        "latest_summary": latest_summary(name or "all", include_global=bool(name)),
        "recent_messages": recent_messages,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
