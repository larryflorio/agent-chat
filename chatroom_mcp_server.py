from __future__ import annotations

import atexit
import json
import os
import re
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
CHATROOM_DIR = ROOT / ".chatroom_v2"
MESSAGES_PATH = CHATROOM_DIR / "messages.jsonl"
PARTICIPANTS_PATH = CHATROOM_DIR / "participants.json"
CURSORS_PATH = CHATROOM_DIR / "cursors.json"
SUMMARIES_PATH = CHATROOM_DIR / "summaries.jsonl"
TOPICS_PATH = CHATROOM_DIR / "topics.json"
GITIGNORE_PATH = ROOT / ".gitignore"
ACTIVE_NAMES: set[str] = set()
MAX_READ_LIMIT = 100
TOPIC_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
TOPIC_STATUS_VALUES = {"open", "closed", "all"}


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


def require_topic_id(value: str) -> str:
    topic_id = require_text(value, "topic_id")
    if not TOPIC_ID_PATTERN.fullmatch(topic_id):
        raise ValueError(
            "topic_id must match ^[a-z0-9][a-z0-9._-]{0,63}$"
        )
    return topic_id


def require_status(value: str) -> str:
    status = require_text(value, "status")
    if status not in TOPIC_STATUS_VALUES:
        raise ValueError("status must be one of: open, closed, all")
    return status


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
    for path in (PARTICIPANTS_PATH, CURSORS_PATH, TOPICS_PATH):
        ensure_json_file(path)
    with locked_file(GITIGNORE_PATH, "a+", fcntl.LOCK_EX) as fp:
        fp.seek(0)
        text = fp.read()
        if ".chatroom_v2/" not in text.splitlines():
            fp.seek(0, os.SEEK_END)
            if text and not text.endswith("\n"):
                fp.write("\n")
            fp.write(".chatroom_v2/\n")
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


def sort_topics(topics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        topics,
        key=lambda topic: (
            topic.get("last_activity_ts") or "",
            topic["id"],
        ),
        reverse=True,
    )


def require_topic(topic_id: str) -> dict[str, Any]:
    topic_id = require_topic_id(topic_id)
    topics = load_json_map(TOPICS_PATH, "topics.json")
    topic = topics.get(topic_id)
    if not isinstance(topic, dict):
        raise ValueError(f"unknown topic_id: {topic_id}")
    return dict(topic)


def require_open_topic(topic_id: str) -> dict[str, Any]:
    topic = require_topic(topic_id)
    if topic["status"] != "open":
        raise ValueError(f"topic {topic_id!r} is closed")
    return topic


def touch_topic(topic_id: str, ts: str | None = None) -> dict[str, Any]:
    topic_id = require_topic_id(topic_id)
    ts = ts or utc_now()

    def updater(data: dict[str, Any]) -> dict[str, Any]:
        topic = data.get(topic_id)
        if not isinstance(topic, dict):
            raise ValueError(f"unknown topic_id: {topic_id}")
        topic["last_activity_ts"] = ts
        return dict(topic)

    return update_json_map(TOPICS_PATH, "topics.json", updater)


def scan_messages(topic_id: str, participant: str = "") -> tuple[list[dict[str, Any]], int, str | None]:
    topic_id = require_topic_id(topic_id)
    visible: list[dict[str, Any]] = []
    latest_id = 0
    last_activity_ts = None
    with locked_file(MESSAGES_PATH, "r", fcntl.LOCK_SH) as fp:
        for line in fp:
            if not line.strip():
                continue
            message = json.loads(line)
            if message.get("topic_id") != topic_id:
                continue
            latest_id = message["id"]
            last_activity_ts = message["ts"]
            if participant and message["to"] not in {"all", participant}:
                continue
            visible.append(
                {
                    "id": message["id"],
                    "ts": message["ts"],
                    "topic_id": message["topic_id"],
                    "from": message["from"],
                    "to": message["to"],
                    "content": message["content"],
                }
            )
    return visible, latest_id, last_activity_ts


def latest_summary(
    topic_id: str,
    scope: str = "",
    include_global: bool = False,
) -> dict[str, Any] | None:
    topic_id = require_topic_id(topic_id)
    target = {scope} if scope else {"all"}
    if include_global and scope:
        target.add("all")
    found = None
    with locked_file(SUMMARIES_PATH, "r", fcntl.LOCK_SH) as fp:
        for line in fp:
            if not line.strip():
                continue
            summary = json.loads(line)
            if summary.get("topic_id") != topic_id:
                continue
            if summary["scope"] in target:
                found = {
                    "id": summary["id"],
                    "ts": summary["ts"],
                    "topic_id": summary["topic_id"],
                    "from": summary["from"],
                    "scope": summary["scope"],
                    "content": summary["content"],
                }
    return found


def get_cursor_value(name: str, topic_id: str) -> int:
    name = require_text(name, "name")
    topic_id = require_topic_id(topic_id)
    per_name = load_json_map(CURSORS_PATH, "cursors.json").get(name, {})
    if per_name in (None, ""):
        per_name = {}
    if not isinstance(per_name, dict):
        raise ValueError("cursors.json must map participant names to topic cursor objects")
    value = per_name.get(topic_id, 0)
    if not isinstance(value, int) or value < 0:
        raise ValueError("topic cursors must contain non-negative integer values")
    return value


def set_cursor_value(name: str, topic_id: str, message_id: int) -> int:
    name = require_text(name, "name")
    topic_id = require_topic_id(topic_id)

    def updater(data: dict[str, Any]) -> int:
        current = data.get(name, {})
        if current in (None, ""):
            current = {}
        if not isinstance(current, dict):
            raise ValueError("cursors.json must map participant names to topic cursor objects")
        existing = current.get(topic_id, 0)
        if not isinstance(existing, int) or existing < 0:
            raise ValueError("topic cursors must contain non-negative integer values")
        current[topic_id] = max(existing, message_id)
        data[name] = current
        return current[topic_id]

    return update_json_map(CURSORS_PATH, "cursors.json", updater)


def latest_room_activity_ts() -> str | None:
    topics = load_json_map(TOPICS_PATH, "topics.json")
    activity_values = []
    for topic in topics.values():
        if isinstance(topic, dict) and topic.get("last_activity_ts"):
            activity_values.append(topic["last_activity_ts"])
    return max(activity_values) if activity_values else None


def list_topic_records(name: str = "", status: str = "open") -> list[dict[str, Any]]:
    name = strip_text(name, "name")
    status = require_status(status)
    topics_data = load_json_map(TOPICS_PATH, "topics.json")
    records: list[dict[str, Any]] = []
    for topic_id, topic in topics_data.items():
        if not isinstance(topic, dict):
            raise ValueError("topics.json must map topic ids to topic objects")
        if status != "all" and topic.get("status") != status:
            continue
        record = {
            "id": topic_id,
            "title": topic["title"],
            "status": topic["status"],
            "created_by": topic["created_by"],
            "created_at": topic["created_at"],
            "closed_at": topic.get("closed_at"),
            "last_activity_ts": topic.get("last_activity_ts"),
        }
        _, latest_message_id, _ = scan_messages(topic_id)
        record["latest_message_id"] = latest_message_id
        if name:
            cursor = get_cursor_value(name, topic_id)
            visible, _, _ = scan_messages(topic_id, name)
            record["cursor"] = cursor
            record["unread_count"] = len([message for message in visible if message["id"] > cursor])
            record["latest_summary"] = latest_summary(topic_id, name, include_global=True)
        records.append(record)
    return sort_topics(records)


def leave_internal(name: str) -> bool:
    ensure_state()
    removed = update_json_map(
        PARTICIPANTS_PATH,
        "participants.json",
        lambda data: bool(data.pop(name, None)),
    )
    ACTIVE_NAMES.discard(name)
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
            raise ValueError(
                f"participant {name!r} is already active; choose a different name or remove the stale participant"
            )
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
    """Remove this agent from active participants."""
    return {"left": leave_internal(require_text(name, "name"))}


@mcp.tool()
def open_topic(topic_id: str, title: str) -> dict[str, Any]:
    """Create a new open topic with a stable identifier."""
    ensure_state()
    topic_id = require_topic_id(topic_id)
    title = require_text(title, "title")
    now = utc_now()

    def updater(data: dict[str, Any]) -> dict[str, Any]:
        if topic_id in data:
            raise ValueError(f"topic {topic_id!r} already exists")
        record = {
            "id": topic_id,
            "title": title,
            "status": "open",
            "created_by": "system",
            "created_at": now,
            "closed_at": None,
            "last_activity_ts": now,
        }
        data[topic_id] = record
        return dict(record)

    return update_json_map(TOPICS_PATH, "topics.json", updater)


@mcp.tool()
def close_topic(topic_id: str) -> dict[str, bool]:
    """Mark an existing topic as closed and read-only."""
    ensure_state()
    topic_id = require_topic_id(topic_id)
    now = utc_now()

    def updater(data: dict[str, Any]) -> bool:
        topic = data.get(topic_id)
        if not isinstance(topic, dict):
            raise ValueError(f"unknown topic_id: {topic_id}")
        if topic["status"] == "closed":
            return False
        topic["status"] = "closed"
        topic["closed_at"] = now
        topic["last_activity_ts"] = now
        return True

    return {"closed": update_json_map(TOPICS_PATH, "topics.json", updater)}


@mcp.tool()
def list_topics(name: str = "", status: str = "open") -> list[dict[str, Any]]:
    """List topic records, optionally annotated with participant unread state."""
    ensure_state()
    return list_topic_records(name=name, status=status)


@mcp.tool()
def send_message(name: str, topic_id: str, content: str, to: str = "all") -> dict[str, int]:
    """Append a broadcast or directed message to a specific topic."""
    ensure_state()
    topic = require_open_topic(topic_id)
    ts = utc_now()
    record_id = append_jsonl(
        MESSAGES_PATH,
        {
            "ts": ts,
            "topic_id": topic["id"],
            "from": require_text(name, "name"),
            "to": require_text(to, "to"),
            "content": require_text(content, "content"),
        },
    )
    touch_topic(topic["id"], ts)
    return {"id": record_id}


@mcp.tool()
def read_messages(
    topic_id: str,
    since_id: int = 0,
    limit: int = 50,
    participant: str = "",
) -> list[dict[str, Any]]:
    """Read recent messages for one topic, optionally filtered by participant visibility."""
    if since_id < 0:
        raise ValueError("since_id must be >= 0")
    ensure_state()
    require_topic(topic_id)
    participant = strip_text(participant, "participant")
    limit = require_window(limit, "limit")
    visible, _, _ = scan_messages(topic_id, participant)
    return [message for message in visible if message["id"] > since_id][:limit]


@mcp.tool()
def list_participants() -> list[dict[str, str]]:
    """List active chatroom participants sorted by name."""
    ensure_state()
    return sort_participants(load_json_map(PARTICIPANTS_PATH, "participants.json"))


@mcp.tool()
def get_status() -> dict[str, Any]:
    """Return aggregate participant, topic, and message status for the chatroom."""
    ensure_state()
    participant_count = len(load_json_map(PARTICIPANTS_PATH, "participants.json"))
    topics = load_json_map(TOPICS_PATH, "topics.json")
    if not isinstance(topics, dict):
        raise ValueError("topics.json must contain a JSON object")
    topic_count = 0
    open_topic_count = 0
    for topic in topics.values():
        if not isinstance(topic, dict):
            raise ValueError("topics.json must map topic ids to topic objects")
        topic_count += 1
        if topic.get("status") == "open":
            open_topic_count += 1
    with locked_file(MESSAGES_PATH, "r", fcntl.LOCK_SH) as fp:
        message_count = sum(1 for line in fp if line.strip())
    return {
        "participant_count": participant_count,
        "topic_count": topic_count,
        "open_topic_count": open_topic_count,
        "message_count": message_count,
        "last_activity_ts": latest_room_activity_ts(),
    }


@mcp.tool()
def get_cursor(name: str, topic_id: str) -> dict[str, int | str]:
    """Return the stored unread cursor for one participant within one topic."""
    ensure_state()
    name = require_text(name, "name")
    topic_id = require_topic_id(topic_id)
    require_topic(topic_id)
    return {"name": name, "topic_id": topic_id, "last_read_id": get_cursor_value(name, topic_id)}


@mcp.tool()
def set_cursor(name: str, topic_id: str, message_id: int) -> dict[str, int | str]:
    """Advance a topic cursor to a specific message id without allowing regression."""
    ensure_state()
    name = require_text(name, "name")
    topic_id = require_topic_id(topic_id)
    require_topic(topic_id)
    if message_id < 0:
        raise ValueError("message_id must be >= 0")
    _, latest_id, _ = scan_messages(topic_id)
    if message_id > latest_id:
        raise ValueError("message_id cannot exceed the latest message id for this topic")
    return {
        "name": name,
        "topic_id": topic_id,
        "last_read_id": set_cursor_value(name, topic_id, message_id),
    }


@mcp.tool()
def read_unread(name: str, topic_id: str, limit: int = 50, mark_read: bool = True) -> dict[str, Any]:
    """Read unread messages for one participant within one topic."""
    ensure_state()
    name = require_text(name, "name")
    topic_id = require_topic_id(topic_id)
    require_topic(topic_id)
    limit = require_window(limit, "limit")
    cursor = get_cursor_value(name, topic_id)
    visible, _, _ = scan_messages(topic_id, name)
    messages = [message for message in visible if message["id"] > cursor][:limit]
    if mark_read and messages:
        cursor = set_cursor_value(name, topic_id, messages[-1]["id"])
    return {
        "name": name,
        "topic_id": topic_id,
        "last_read_id": cursor,
        "messages": messages,
    }


@mcp.tool()
def write_summary(name: str, topic_id: str, content: str, scope: str = "all") -> dict[str, int]:
    """Persist a summary record for one topic and scope."""
    ensure_state()
    topic = require_open_topic(topic_id)
    ts = utc_now()
    summary_id = append_jsonl(
        SUMMARIES_PATH,
        {
            "ts": ts,
            "topic_id": topic["id"],
            "from": require_text(name, "name"),
            "scope": require_text(scope, "scope"),
            "content": require_text(content, "content"),
        },
    )
    touch_topic(topic["id"], ts)
    return {"id": summary_id}


@mcp.tool()
def read_latest_summary(topic_id: str, scope: str = "all") -> dict[str, Any] | None:
    """Return the latest summary for one topic whose scope exactly matches the request."""
    ensure_state()
    topic_id = require_topic_id(topic_id)
    require_topic(topic_id)
    return latest_summary(topic_id, require_text(scope, "scope"))


@mcp.tool()
def get_handoff(name: str, topic_id: str, recent_limit: int = 10) -> dict[str, Any]:
    """Return a compact orientation payload for one participant resuming one topic."""
    ensure_state()
    name = require_text(name, "name")
    topic_id = require_topic_id(topic_id)
    topic = require_topic(topic_id)
    recent_limit = require_window(recent_limit, "recent_limit")
    participants = sort_participants(load_json_map(PARTICIPANTS_PATH, "participants.json"))
    visible, latest_id, _ = scan_messages(topic_id, name)
    cursor = get_cursor_value(name, topic_id)
    return {
        "participants": participants,
        "topic": topic,
        "latest_message_id": latest_id,
        "cursor": cursor,
        "unread_count": len([message for message in visible if message["id"] > cursor]),
        "latest_summary": latest_summary(topic_id, name, include_global=True),
        "recent_messages": visible[-recent_limit:],
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
