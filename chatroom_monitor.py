from __future__ import annotations

import argparse
import json
import os
import shutil
import textwrap
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import fcntl


def resolve_root() -> Path:
    override = os.environ.get("CHATROOM_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parent


ROOT = resolve_root()
CHATROOM_DIR = ROOT / ".chatroom_v2"
MESSAGES_PATH = CHATROOM_DIR / "messages.jsonl"
PARTICIPANTS_PATH = CHATROOM_DIR / "participants.json"
TOPICS_PATH = CHATROOM_DIR / "topics.json"
SUMMARIES_PATH = CHATROOM_DIR / "summaries.jsonl"
CURSORS_PATH = CHATROOM_DIR / "cursors.json"


def file_signature(path: Path) -> tuple[bool, int | None, int | None]:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return False, None, None
    return True, stat.st_mtime_ns, stat.st_size


@contextmanager
def locked_file(path: Path) -> Iterator[Any]:
    with path.open("r", encoding="utf-8") as fp:
        fcntl.flock(fp.fileno(), fcntl.LOCK_SH)
        try:
            yield fp
        finally:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)


def load_json_object(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, None
    try:
        with locked_file(path) as fp:
            data = json.loads(fp.read() or "{}")
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError) as exc:
        return {}, f"{path.name} error: {exc}"
    if not isinstance(data, dict):
        return {}, f"{path.name} error: expected a JSON object"
    return data, None


def normalize_participant_record(name: str, record: object) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(record, dict):
        return None
    participant_name = str(record.get("name", name)).strip()
    if not participant_name:
        return None
    normalized = dict(record)
    normalized["name"] = participant_name
    normalized["role"] = str(normalized.get("role", ""))
    return participant_name, normalized


def load_participants() -> tuple[list[dict[str, Any]], str | None]:
    data, error = load_json_object(PARTICIPANTS_PATH)
    if error:
        return [], error
    participants: list[dict[str, Any]] = []
    try:
        if all(isinstance(value, dict) for value in data.values()):
            records = []
            for key, value in data.items():
                normalized = normalize_participant_record(str(key), value)
                if normalized is None:
                    return [], "participants.json error: participant records must include a name"
                records.append(normalized[1])
            participants = sorted(records, key=lambda record: record["name"])
        else:
            for record in data.values():
                if not isinstance(record, dict):
                    return [], "participants.json error: participant records must be JSON objects"
                normalized = normalize_participant_record(str(record.get("name", "")).strip(), record)
                if normalized is None:
                    return [], "participants.json error: participant records must include a name"
                participants.append(normalized[1])
            participants.sort(key=lambda record: record["name"])
    except (TypeError, ValueError, KeyError) as exc:
        return [], f"participants.json error: {exc}"
    return participants, None


def normalize_topic_record(topic_id: str, record: object) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    normalized = dict(record)
    normalized["id"] = str(normalized.get("id", topic_id)).strip() or topic_id
    normalized["title"] = str(normalized.get("title", normalized["id"]))
    normalized["status"] = str(normalized.get("status", "open"))
    normalized["created_by"] = str(normalized.get("created_by", ""))
    normalized["created_at"] = str(normalized.get("created_at", ""))
    closed_at = normalized.get("closed_at")
    normalized["closed_at"] = None if closed_at in {"", "null"} else closed_at
    last_activity_ts = normalized.get("last_activity_ts")
    normalized["last_activity_ts"] = None if last_activity_ts in {"", "null"} else last_activity_ts
    return normalized


def load_topics() -> tuple[dict[str, dict[str, Any]], str | None]:
    data, error = load_json_object(TOPICS_PATH)
    if error:
        return {}, error
    topics: dict[str, dict[str, Any]] = {}
    try:
        for topic_id, record in data.items():
            normalized = normalize_topic_record(str(topic_id), record)
            if normalized is None:
                return {}, "topics.json error: topic records must be JSON objects"
            topics[normalized["id"]] = normalized
    except (TypeError, ValueError, KeyError) as exc:
        return {}, f"topics.json error: {exc}"
    return topics, None


def load_cursors() -> tuple[dict[str, dict[str, int]], str | None]:
    data, error = load_json_object(CURSORS_PATH)
    if error:
        return {}, error
    cursors: dict[str, dict[str, int]] = {}
    try:
        for participant, topic_map in data.items():
            if not isinstance(topic_map, dict):
                return {}, "cursors.json error: cursor maps must be JSON objects"
            participant_name = str(participant)
            cursors[participant_name] = {}
            for topic_id, message_id in topic_map.items():
                cursors[participant_name][str(topic_id)] = int(message_id)
    except (TypeError, ValueError) as exc:
        return {}, f"cursors.json error: {exc}"
    return cursors, None


def read_message_log() -> tuple[list[dict[str, Any]], str | None]:
    if not MESSAGES_PATH.exists():
        return [], None
    messages: list[dict[str, Any]] = []
    try:
        with locked_file(MESSAGES_PATH) as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                message = json.loads(line)
                if not isinstance(message, dict):
                    return [], "messages.jsonl error: messages must be JSON objects"
                messages.append(message)
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError) as exc:
        return [], f"messages.jsonl error: {exc}"
    return messages, None


def read_summary_log() -> tuple[list[dict[str, Any]], str | None]:
    if not SUMMARIES_PATH.exists():
        return [], None
    summaries: list[dict[str, Any]] = []
    try:
        with locked_file(SUMMARIES_PATH) as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                summary = json.loads(line)
                if not isinstance(summary, dict):
                    return [], "summaries.jsonl error: summaries must be JSON objects"
                summaries.append(summary)
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError) as exc:
        return [], f"summaries.jsonl error: {exc}"
    return summaries, None


def message_topic_id(message: dict[str, Any]) -> str:
    return str(message.get("topic_id", "")).strip()


def message_visible_to_participant(message: dict[str, Any], participant: str) -> bool:
    if not participant:
        return True
    target = str(message.get("to", "all"))
    return target in {"all", participant}


def load_messages(
    limit: int,
    participant: str,
    since_id: int = 0,
    topic_id: str = "",
) -> tuple[list[dict[str, Any]], int, str | None, str | None]:
    messages, error = read_message_log()
    if error:
        return [], 0, None, error
    total_count = len(messages)
    last_activity_ts = messages[-1].get("ts") if messages else None
    filtered: list[dict[str, Any]] = []
    for message in messages:
        if topic_id and message_topic_id(message) != topic_id:
            continue
        if participant and not message_visible_to_participant(message, participant):
            continue
        try:
            if int(message.get("id", 0)) <= since_id:
                continue
        except (TypeError, ValueError, KeyError) as exc:
            return [], 0, None, f"messages.jsonl error: {exc}"
        filtered.append(message)
    if since_id:
        return filtered, total_count, last_activity_ts, None
    return filtered[-limit:], total_count, last_activity_ts, None


def fit(text: str, width: int) -> str:
    if width <= 3 or len(text) <= width:
        return text
    return text[: max(0, width - 3)] + "..."


def render_participants(participants: list[dict[str, Any]], width: int) -> list[str]:
    if not participants:
        return ["Participants: none"]
    chunks = [f"{p['name']} ({p['role'] or 'general'})" for p in participants]
    return ["Participants: " + fit(", ".join(chunks), width - 14)]


def render_messages(messages: list[dict[str, Any]], width: int) -> list[str]:
    lines: list[str] = []
    if not messages:
        return ["No messages yet."]
    for message in messages:
        target = "all" if str(message.get("to", "all")) == "all" else f"@{message['to']}"
        prefix = f"[{int(message.get('id', 0)):>4}] {message.get('ts', '')} {message.get('from', '')} -> {target}"
        lines.append(fit(prefix, width))
        wrapped = textwrap.wrap(
            str(message.get("content", "")),
            width=max(20, width - 2),
            initial_indent="  ",
            subsequent_indent="  ",
            replace_whitespace=False,
        )
        lines.extend(wrapped or ["  "])
    return lines


def summary_scope_label(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "none"
    scope = str(summary.get("scope", "all"))
    return scope or "all"


def summary_text(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "none"
    return str(summary.get("content", "")).strip() or "none"


def coerce_topic_record(topic_id: str, record: dict[str, Any] | None) -> dict[str, Any]:
    base = {
        "id": topic_id,
        "title": topic_id,
        "status": "open",
        "created_by": "",
        "created_at": "",
        "closed_at": None,
        "last_activity_ts": None,
    }
    if record:
        base.update(record)
    base["id"] = str(base.get("id", topic_id)) or topic_id
    base["title"] = str(base.get("title", base["id"]))
    base["status"] = str(base.get("status", "open"))
    base["created_by"] = str(base.get("created_by", ""))
    base["created_at"] = str(base.get("created_at", ""))
    closed_at = base.get("closed_at")
    base["closed_at"] = None if closed_at in {"", "null"} else closed_at
    last_activity_ts = base.get("last_activity_ts")
    base["last_activity_ts"] = None if last_activity_ts in {"", "null"} else last_activity_ts
    return base


def state_messages(state: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    if not CHATROOM_DIR.exists():
        messages.append("Waiting for chatroom_v2 initialization...")
    for error in (
        state.get("participants_error"),
        state.get("topics_error"),
        state.get("messages_error"),
        state.get("summaries_error"),
        state.get("cursors_error"),
    ):
        if error:
            messages.append(str(error))
    return messages


def load_cached_state(args: argparse.Namespace, cache: dict[str, Any]) -> dict[str, Any]:
    signatures = {
        "participants_sig": file_signature(PARTICIPANTS_PATH),
        "topics_sig": file_signature(TOPICS_PATH),
        "messages_sig": file_signature(MESSAGES_PATH),
        "summaries_sig": file_signature(SUMMARIES_PATH),
        "cursors_sig": file_signature(CURSORS_PATH),
    }
    if any(signatures[key] != cache.get(key) for key in signatures):
        participants, participants_error = load_participants()
        topics, topics_error = load_topics()
        messages, messages_error = read_message_log()
        summaries, summaries_error = read_summary_log()
        cursors, cursors_error = load_cursors()
        cache.update(signatures)
        cache.update(
            {
                "participants": participants,
                "participants_error": participants_error,
                "topics": topics,
                "topics_error": topics_error,
                "messages": messages,
                "messages_error": messages_error,
                "summaries": summaries,
                "summaries_error": summaries_error,
                "cursors": cursors,
                "cursors_error": cursors_error,
            }
        )
    return cache


def topic_ids_from_state(state: dict[str, Any]) -> set[str]:
    topic_ids = {str(topic_id) for topic_id in state.get("topics", {})}
    for message in state.get("messages", []):
        topic_id = message_topic_id(message)
        if topic_id:
            topic_ids.add(topic_id)
    for summary in state.get("summaries", []):
        topic_id = str(summary.get("topic_id", "")).strip()
        if topic_id:
            topic_ids.add(topic_id)
    for participant_map in state.get("cursors", {}).values():
        for topic_id in participant_map:
            topic_ids.add(str(topic_id))
    return topic_ids


def latest_summary_index(summaries: list[dict[str, Any]]) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, dict[str, Any]]]:
    by_topic_scope: dict[tuple[str, str], dict[str, Any]] = {}
    by_topic: dict[str, dict[str, Any]] = {}
    for summary in summaries:
        topic_id = str(summary.get("topic_id", "")).strip()
        if not topic_id:
            continue
        scope = str(summary.get("scope", "all")).strip() or "all"
        by_topic_scope[(topic_id, scope)] = summary
        by_topic[topic_id] = summary
    return by_topic_scope, by_topic


def topic_last_activity(topics: dict[str, dict[str, Any]], messages_by_topic: dict[str, list[dict[str, Any]]]) -> dict[str, str | None]:
    last_activity: dict[str, str | None] = {}
    for topic_id, record in topics.items():
        last_activity[topic_id] = record.get("last_activity_ts") or record.get("created_at") or None
    for topic_id, messages in messages_by_topic.items():
        if not messages:
            continue
        last_activity[topic_id] = messages[-1].get("ts") or last_activity.get(topic_id)
    return last_activity


def build_view_model(args: argparse.Namespace, state: dict[str, Any]) -> dict[str, Any]:
    participants = state.get("participants", [])
    participant_filter = args.participant.strip()
    status_filter = args.status
    topic_filter = args.topic.strip()
    messages = state.get("messages", [])
    summaries = state.get("summaries", [])
    cursors = state.get("cursors", {})
    topic_map = {topic_id: coerce_topic_record(topic_id, record) for topic_id, record in state.get("topics", {}).items()}
    observed_topic_ids = topic_ids_from_state(state)
    for topic_id in observed_topic_ids:
        topic_map.setdefault(topic_id, coerce_topic_record(topic_id, None))

    messages_by_topic: dict[str, list[dict[str, Any]]] = {topic_id: [] for topic_id in topic_map}
    for message in messages:
        topic_id = message_topic_id(message)
        if not topic_id:
            continue
        messages_by_topic.setdefault(topic_id, []).append(message)
    for topic_id, topic_messages in messages_by_topic.items():
        topic_messages.sort(key=lambda message: int(message.get("id", 0)))

    latest_summary_by_topic_scope, latest_summary_by_topic = latest_summary_index(summaries)
    last_activity = topic_last_activity(topic_map, messages_by_topic)
    for topic_id, topic_record in topic_map.items():
        topic_record["last_activity_ts"] = last_activity.get(topic_id)

    overview_topics = list(topic_map.values())
    if status_filter != "all":
        overview_topics = [topic for topic in overview_topics if topic["status"] == status_filter]
    overview_topics.sort(key=lambda topic: topic["id"])
    overview_topics.sort(key=lambda topic: topic.get("last_activity_ts") or "", reverse=True)
    if args.limit:
        overview_topics = overview_topics[: args.limit]

    topic_rows: list[dict[str, Any]] = []
    for topic in overview_topics:
        topic_id = topic["id"]
        topic_messages = messages_by_topic.get(topic_id, [])
        latest_message_id = int(topic_messages[-1]["id"]) if topic_messages else 0
        summary = latest_summary_by_topic_scope.get((topic_id, "all")) or latest_summary_by_topic.get(topic_id)
        unread_count = None
        cursor = None
        if participant_filter:
            cursor = int(cursors.get(participant_filter, {}).get(topic_id, 0))
            unread_count = sum(
                1
                for message in topic_messages
                if int(message.get("id", 0)) > cursor and message_visible_to_participant(message, participant_filter)
            )
        topic_rows.append(
            {
                **topic,
                "message_count": len(topic_messages),
                "latest_message_id": latest_message_id,
                "latest_summary": summary,
                "unread_count": unread_count,
                "cursor": cursor,
            }
        )

    selected_topic = coerce_topic_record(topic_filter, topic_map.get(topic_filter)) if topic_filter else None
    if topic_filter and topic_filter not in topic_map:
        selected_topic = coerce_topic_record(topic_filter, None)
    selected_messages: list[dict[str, Any]] = []
    selected_summary: dict[str, Any] | None = None
    selected_cursor = None
    selected_unread_count = None
    if topic_filter:
        selected_topic_messages = list(messages_by_topic.get(topic_filter, []))
        if participant_filter:
            selected_topic_messages = [message for message in selected_topic_messages if message_visible_to_participant(message, participant_filter)]
            selected_cursor = int(cursors.get(participant_filter, {}).get(topic_filter, 0))
            selected_unread_count = sum(
                1 for message in selected_topic_messages if int(message.get("id", 0)) > selected_cursor
            )
        if args.limit:
            selected_messages = selected_topic_messages[-args.limit:]
        else:
            selected_messages = selected_topic_messages
        selected_summary = latest_summary_by_topic_scope.get((topic_filter, "all")) or latest_summary_by_topic.get(topic_filter)
    room_status = {
        "participant_count": len(participants),
        "topic_count": len(topic_map),
        "open_topic_count": sum(1 for topic in topic_map.values() if topic["status"] == "open"),
        "message_count": len(messages),
        "last_activity_ts": max((topic.get("last_activity_ts") or "" for topic in topic_map.values()), default="") or None,
    }
    return {
        "mode": "topic" if topic_filter else "overview",
        "root": str(ROOT),
        "status_filter": status_filter,
        "participant_filter": participant_filter or None,
        "topic_filter": topic_filter or None,
        "participants": participants,
        "topics": topic_rows,
        "topic": selected_topic,
        "messages": selected_messages,
        "latest_summary": selected_summary,
        "cursor": selected_cursor,
        "unread_count": selected_unread_count,
        "status": room_status,
        "state_messages": state_messages(state),
    }


def render_topic_row(topic: dict[str, Any], participant_filter: str, width: int) -> str:
    unread = topic.get("unread_count")
    unread_text = f"unread: {unread}" if unread is not None else "unread: -"
    summary = summary_text(topic.get("latest_summary"))
    scope = summary_scope_label(topic.get("latest_summary"))
    summary_part = f"summary[{scope}]: {summary}"
    return fit(
        (
            f"- [{topic['status']}] {topic['id']} | {unread_text} | "
            f"messages: {topic['message_count']} | last: {topic.get('last_activity_ts') or 'none'} | {summary_part}"
        ),
        width,
    )


def render_text_lines(args: argparse.Namespace, view: dict[str, Any], width: int) -> list[str]:
    lines = [
        "Agent Chatroom Monitor",
        fit(f"Repo: {ROOT}", width),
    ]
    if view["mode"] == "topic":
        lines.append(
            f"View: topic {view['topic_filter']} | Participant filter: {view['participant_filter'] or 'none'} | Format: {args.format}"
        )
    else:
        lines.append(
            f"View: overview | Status filter: {view['status_filter']} | Participant filter: {view['participant_filter'] or 'none'} | Format: {args.format}"
        )
    lines.append(
        fit(
            (
                f"Status: participants {view['status']['participant_count']} | topics {view['status']['topic_count']} | "
                f"open {view['status']['open_topic_count']} | messages {view['status']['message_count']} | "
                f"last activity: {view['status']['last_activity_ts'] or 'none'}"
            ),
            width,
        )
    )
    for message in view["state_messages"]:
        lines.append(fit(f"State: {message}", width))
    lines.append("-" * min(width, 80))
    lines.extend(render_participants(view["participants"], width))
    lines.append("-" * min(width, 80))
    if view["mode"] == "overview":
        lines.append(f"Topics (showing up to {args.limit}):")
        if not view["topics"]:
            lines.append("No topics yet.")
        else:
            for topic in view["topics"]:
                lines.append(render_topic_row(topic, view["participant_filter"] or "", width))
    else:
        topic = view["topic"]
        if not topic:
            lines.append("Topic: missing")
        else:
            lines.append(f"Topic: {topic['id']} [{topic['status']}]")
            lines.append(fit(f"Title: {topic['title']}", width))
            lines.append(fit(f"Created by: {topic['created_by'] or 'unknown'}", width))
            lines.append(fit(f"Created at: {topic['created_at'] or 'unknown'}", width))
            lines.append(fit(f"Last activity: {topic.get('last_activity_ts') or 'none'}", width))
        if view["participant_filter"]:
            lines.append(
                fit(
                    f"Viewer participant: {view['participant_filter']} | Cursor: {view['cursor'] or 0} | Unread: {view['unread_count'] or 0}",
                    width,
                )
            )
        lines.append("-" * min(width, 80))
        lines.append("Latest summary:")
        lines.append(f"  [{summary_scope_label(view['latest_summary'])}] {summary_text(view['latest_summary'])}")
        lines.append("-" * min(width, 80))
        lines.append(f"Recent messages (showing up to {args.limit}):")
        lines.extend(render_messages(view["messages"], width))
    lines.append("")
    lines.append("Ctrl-C to exit")
    return lines


def render_text_snapshot(args: argparse.Namespace, view: dict[str, Any], width: int) -> str:
    return "\x1b[2J\x1b[H" + "\n".join(render_text_lines(args, view, width))


def render_json_snapshot(args: argparse.Namespace, view: dict[str, Any]) -> str:
    payload = {
        "mode": view["mode"],
        "root": view["root"],
        "participant_filter": view["participant_filter"],
        "status_filter": view["status_filter"],
        "status": view["status"],
        "participants": view["participants"],
        "topics": view["topics"],
        "topic": view["topic"],
        "messages": view["messages"],
        "latest_summary": view["latest_summary"],
        "cursor": view["cursor"],
        "unread_count": view["unread_count"],
        "state_messages": view["state_messages"],
        "limit": args.limit,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def snapshot_frame(args: argparse.Namespace, state: dict[str, Any]) -> str:
    width = shutil.get_terminal_size((100, 24)).columns
    view = build_view_model(args, state)
    return render_text_snapshot(args, view, width)


def live_status_lines(args: argparse.Namespace, state: dict[str, Any], width: int) -> list[str]:
    view = build_view_model(args, state)
    lines = [
        fit(
            (
                f"Status | participants {view['status']['participant_count']} | topics {view['status']['topic_count']} | "
                f"open {view['status']['open_topic_count']} | messages {view['status']['message_count']} | "
                f"last activity: {view['status']['last_activity_ts'] or 'none'}"
            ),
            width,
        )
    ]
    lines.extend(fit(f"State | {message}", width) for message in view["state_messages"])
    lines.extend(fit(line, width) for line in render_participants(view["participants"], width))
    if view["mode"] == "topic" and view["topic"]:
        topic = view["topic"]
        lines.append(fit(f"Topic | {topic['id']} [{topic['status']}]", width))
        lines.append(fit(f"Title | {topic['title']}", width))
    return lines


def print_live_header(args: argparse.Namespace, state: dict[str, Any], width: int) -> None:
    view = build_view_model(args, state)
    lines = [
        "Agent Chatroom Monitor",
        fit(f"Repo: {ROOT}", width),
    ]
    if view["mode"] == "topic":
        lines.append(
            f"View: topic {view['topic_filter']} | Participant filter: {view['participant_filter'] or 'none'} | Format: {args.format}"
        )
    else:
        lines.append(
            f"View: overview | Status filter: {view['status_filter']} | Participant filter: {view['participant_filter'] or 'none'} | Format: {args.format}"
        )
    lines.append("-" * min(width, 80))
    lines.extend(live_status_lines(args, state, width))
    lines.append("-" * min(width, 80))
    print("\n".join(lines), flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only terminal viewer for the agent chatroom.")
    parser.add_argument("--limit", type=int, default=30, help="Number of topics or messages to display.")
    parser.add_argument("--interval", type=float, default=2.0, help="Refresh interval in seconds.")
    parser.add_argument("--participant", default="", help="Show participant-aware unread counts and visibility filtering.")
    parser.add_argument("--topic", default="", help="Show a single topic in detail.")
    parser.add_argument(
        "--status",
        choices=("open", "closed", "all"),
        default="open",
        help="Filter topics in overview mode.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Render as human-readable text or structured JSON.",
    )
    parser.add_argument("--once", action="store_true", help="Render one frame and exit.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.limit < 1:
        raise ValueError("--limit must be >= 1")
    if args.interval <= 0:
        raise ValueError("--interval must be > 0")
    args.participant = args.participant.strip()
    args.topic = args.topic.strip()
    cache: dict[str, Any] = {
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
    state = load_cached_state(args, cache)
    width = shutil.get_terminal_size((100, 24)).columns
    view = build_view_model(args, state)
    if args.format == "json":
        rendered = render_json_snapshot(args, view)
    else:
        rendered = render_text_snapshot(args, view, width)
    if args.once:
        print(rendered, end="")
        return
    print(rendered, end="" if rendered.endswith("\n") else "\n", flush=True)
    last_rendered = rendered
    unchanged_polls = 0
    try:
        while True:
            state = load_cached_state(args, cache)
            width = shutil.get_terminal_size((100, 24)).columns
            view = build_view_model(args, state)
            if args.format == "json":
                rendered = render_json_snapshot(args, view)
            else:
                rendered = render_text_snapshot(args, view, width)
            changed = rendered != last_rendered
            if changed:
                print(rendered, end="" if rendered.endswith("\n") else "\n", flush=True)
                last_rendered = rendered
                unchanged_polls = 0
            else:
                unchanged_polls += 1
            sleep_for = args.interval if changed else min(args.interval * (2 ** min(unchanged_polls, 3)), 5.0)
            time.sleep(sleep_for)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
