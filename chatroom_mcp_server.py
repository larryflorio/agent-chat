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
ROOT = Path.cwd()
CHATROOM_DIR = ROOT / ".chatroom"
MESSAGES_PATH = CHATROOM_DIR / "messages.jsonl"
PARTICIPANTS_PATH = CHATROOM_DIR / "participants.json"
GITIGNORE_PATH = ROOT / ".gitignore"
ACTIVE_NAMES: set[str] = set()


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


def ensure_state() -> None:
    CHATROOM_DIR.mkdir(exist_ok=True)
    with MESSAGES_PATH.open("a", encoding="utf-8"):
        pass
    with locked_file(PARTICIPANTS_PATH, "a+", fcntl.LOCK_EX) as fp:
        fp.seek(0)
        if not fp.read():
            fp.seek(0)
            fp.write("{}")
            fp.truncate()
            flush_file(fp)
    with locked_file(GITIGNORE_PATH, "a+", fcntl.LOCK_EX) as fp:
        fp.seek(0)
        text = fp.read()
        if ".chatroom/" not in text.splitlines():
            fp.seek(0, os.SEEK_END)
            if text and not text.endswith("\n"):
                fp.write("\n")
            fp.write(".chatroom/\n")
            flush_file(fp)


def load_participants(fp: Any) -> dict[str, dict[str, str]]:
    fp.seek(0)
    text = fp.read()
    data = json.loads(text or "{}")
    if not isinstance(data, dict):
        raise ValueError("participants.json must contain a JSON object")
    return data


def write_participants(fp: Any, data: dict[str, dict[str, str]]) -> None:
    fp.seek(0)
    fp.write(json.dumps(data, ensure_ascii=False, sort_keys=True))
    fp.truncate()
    flush_file(fp)


def sorted_participants(data: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    return [data[name] for name in sorted(data)]


def append_message(from_name: str, to: str, content: str) -> int:
    with locked_file(MESSAGES_PATH, "a+", fcntl.LOCK_EX) as fp:
        fp.seek(0)
        message_id = sum(1 for _ in fp) + 1
        record = {
            "id": message_id,
            "ts": utc_now(),
            "from": from_name,
            "to": to,
            "content": content,
        }
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        flush_file(fp)
        return message_id


def leave_internal(name: str) -> bool:
    ensure_state()
    removed = False
    with locked_file(PARTICIPANTS_PATH, "r+", fcntl.LOCK_EX) as fp:
        data = load_participants(fp)
        if name in data:
            del data[name]
            write_participants(fp, data)
            removed = True
    ACTIVE_NAMES.discard(name)
    if removed:
        append_message("system", "all", f"{name} left the chatroom")
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
    name = require_text(name, "name")
    role = strip_text(role, "role")
    ensure_state()
    now = utc_now()
    with locked_file(PARTICIPANTS_PATH, "r+", fcntl.LOCK_EX) as fp:
        data = load_participants(fp)
        existing = data.get(name)
        joined_at = existing["joined_at"] if existing else now
        data[name] = {
            "name": name,
            "role": role,
            "joined_at": joined_at,
            "last_seen": now,
        }
        write_participants(fp, data)
        participants = sorted_participants(data)
    ACTIVE_NAMES.add(name)
    return participants


@mcp.tool()
def leave(name: str) -> dict[str, bool]:
    name = require_text(name, "name")
    return {"left": leave_internal(name)}


@mcp.tool()
def send_message(name: str, content: str, to: str = "all") -> dict[str, int]:
    name = require_text(name, "name")
    content = require_text(content, "content")
    to = require_text(to, "to")
    ensure_state()
    return {"id": append_message(name, to, content)}


@mcp.tool()
def read_messages(
    since_id: int = 0, limit: int = 50, participant: str = ""
) -> list[dict[str, Any]]:
    if since_id < 0:
        raise ValueError("since_id must be >= 0")
    if limit < 1:
        raise ValueError("limit must be >= 1")
    participant = strip_text(participant, "participant")
    ensure_state()
    messages: list[dict[str, Any]] = []
    with locked_file(MESSAGES_PATH, "r", fcntl.LOCK_SH) as fp:
        for line in fp:
            message = json.loads(line)
            if message["id"] <= since_id:
                continue
            if participant and message["to"] not in {"all", participant}:
                continue
            messages.append(
                {
                    "id": message["id"],
                    "ts": message["ts"],
                    "from": message["from"],
                    "to": message["to"],
                    "content": message["content"],
                }
            )
            if len(messages) >= limit:
                break
    return messages


@mcp.tool()
def list_participants() -> list[dict[str, str]]:
    ensure_state()
    with locked_file(PARTICIPANTS_PATH, "r", fcntl.LOCK_SH) as fp:
        return sorted_participants(load_participants(fp))


@mcp.tool()
def get_status() -> dict[str, Any]:
    ensure_state()
    with locked_file(PARTICIPANTS_PATH, "r", fcntl.LOCK_SH) as fp:
        participant_count = len(load_participants(fp))
    message_count = 0
    last_activity_ts = None
    with locked_file(MESSAGES_PATH, "r", fcntl.LOCK_SH) as fp:
        for line in fp:
            message_count += 1
            last_activity_ts = json.loads(line)["ts"]
    return {
        "participant_count": participant_count,
        "message_count": message_count,
        "last_activity_ts": last_activity_ts,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
