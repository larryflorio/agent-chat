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
CHATROOM_DIR = ROOT / ".chatroom"
MESSAGES_PATH = CHATROOM_DIR / "messages.jsonl"
PARTICIPANTS_PATH = CHATROOM_DIR / "participants.json"


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


def load_participants() -> tuple[list[dict[str, str]], str | None]:
    if not PARTICIPANTS_PATH.exists():
        return [], None
    try:
        with locked_file(PARTICIPANTS_PATH) as fp:
            data = json.loads(fp.read() or "{}")
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError) as exc:
        return [], f"participants.json error: {exc}"
    if not isinstance(data, dict):
        return [], "participants.json error: expected a JSON object"
    participants: list[dict[str, str]] = []
    for name in sorted(data):
        record = data[name]
        if not isinstance(record, dict):
            return [], "participants.json error: participant records must be JSON objects"
        try:
            participant_name = str(record["name"])
            role = str(record["role"])
        except KeyError as exc:
            return [], f"participants.json error: missing field {exc.args[0]!r}"
        participants.append({"name": participant_name, "role": role})
    return participants, None


def load_messages(limit: int, participant: str, since_id: int = 0) -> tuple[list[dict[str, Any]], int, str | None, str | None]:
    if not MESSAGES_PATH.exists():
        return [], 0, None, None
    total_count = 0
    last_activity_ts = None
    filtered: list[dict[str, Any]] = []
    try:
        with locked_file(MESSAGES_PATH) as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                message = json.loads(line)
                total_count += 1
                last_activity_ts = message["ts"]
                if participant and message["to"] not in {"all", participant}:
                    continue
                if message["id"] <= since_id:
                    continue
                filtered.append(message)
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        return [], 0, None, f"messages.jsonl error: {exc}"
    if since_id:
        return filtered, total_count, last_activity_ts, None
    return filtered[-limit:], total_count, last_activity_ts, None


def fit(text: str, width: int) -> str:
    if width <= 3 or len(text) <= width:
        return text
    return text[: max(0, width - 3)] + "..."


def render_participants(participants: list[dict[str, str]], width: int) -> list[str]:
    if not participants:
        return ["Participants: none"]
    chunks = [f"{p['name']} ({p['role'] or 'general'})" for p in participants]
    return ["Participants: " + fit(", ".join(chunks), width - 14)]


def render_messages(messages: list[dict[str, Any]], width: int) -> list[str]:
    lines: list[str] = []
    if not messages:
        return ["No messages yet."]
    for message in messages:
        target = "all" if message["to"] == "all" else f"@{message['to']}"
        prefix = f"[{message['id']:>4}] {message['ts']} {message['from']} -> {target}"
        lines.append(fit(prefix, width))
        wrapped = textwrap.wrap(
            message["content"],
            width=max(20, width - 2),
            initial_indent="  ",
            subsequent_indent="  ",
            replace_whitespace=False,
        )
        lines.extend(wrapped or ["  "])
    return lines


def load_cached_state(args: argparse.Namespace, cache: dict[str, Any]) -> dict[str, Any]:
    participants_sig = file_signature(PARTICIPANTS_PATH)
    if participants_sig != cache.get("participants_sig"):
        participants, participants_error = load_participants()
        cache["participants_sig"] = participants_sig
        cache["participants"] = participants
        cache["participants_error"] = participants_error

    messages_sig = file_signature(MESSAGES_PATH)
    if messages_sig != cache.get("messages_sig"):
        messages, total_count, last_activity_ts, messages_error = load_messages(args.limit, args.participant)
        cache["messages_sig"] = messages_sig
        cache["messages"] = messages
        cache["total_count"] = total_count
        cache["last_activity_ts"] = last_activity_ts
        cache["messages_error"] = messages_error

    return cache


def state_messages(state: dict[str, Any]) -> list[str]:
    messages: list[str] = []
    if not CHATROOM_DIR.exists():
        messages.append("Waiting for chatroom initialization...")
    for error in (state["participants_error"], state["messages_error"]):
        if error:
            messages.append(error)
    return messages


def snapshot_frame(args: argparse.Namespace, state: dict[str, Any]) -> str:
    width = shutil.get_terminal_size((100, 24)).columns
    participant_filter = args.participant or "none"
    participants = state["participants"]
    messages = state["messages"]
    total_count = state["total_count"]
    last_activity_ts = state["last_activity_ts"]
    current_state_messages = state_messages(state)
    lines = [
        "Agent Chatroom Monitor",
        fit(f"Repo: {ROOT}", width),
        f"Refresh: {args.interval:.1f}s | Participant filter: {participant_filter}",
        f"Participants: {len(participants)} | Messages: {total_count} | Last activity: {last_activity_ts or 'none'}",
        "-" * min(width, 80),
    ]
    lines.extend(fit(f"State: {message}", width) for message in current_state_messages)
    if current_state_messages:
        lines.append("-" * min(width, 80))
    lines.extend(render_participants(participants, width))
    lines.append("-" * min(width, 80))
    lines.append(f"Recent messages (showing up to {args.limit}):")
    lines.extend(render_messages(messages, width))
    lines.append("")
    lines.append("Ctrl-C to exit")
    return "\x1b[2J\x1b[H" + "\n".join(lines)


def live_status_lines(args: argparse.Namespace, state: dict[str, Any], width: int) -> list[str]:
    lines = [
        fit(
            (
                f"Status | Participants: {len(state['participants'])} | Messages: {state['total_count']} | "
                f"Last activity: {state['last_activity_ts'] or 'none'}"
            ),
            width,
        )
    ]
    lines.extend(fit(f"State | {message}", width) for message in state_messages(state))
    lines.extend(fit(line, width) for line in render_participants(state["participants"], width))
    return lines


def print_live_header(args: argparse.Namespace, state: dict[str, Any], width: int) -> None:
    participant_filter = args.participant or "none"
    lines = [
        "Agent Chatroom Monitor",
        fit(f"Repo: {ROOT}", width),
        f"Refresh: {args.interval:.1f}s | Participant filter: {participant_filter}",
        "Follow mode: appending new messages only. Ctrl-C to exit.",
        "-" * min(width, 80),
    ]
    lines.extend(live_status_lines(args, state, width))
    lines.append("-" * min(width, 80))
    print("\n".join(lines), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only terminal monitor for the agent chatroom.")
    parser.add_argument("--limit", type=int, default=30, help="Number of recent messages to display.")
    parser.add_argument("--interval", type=float, default=2.0, help="Refresh interval in seconds.")
    parser.add_argument(
        "--participant",
        default="",
        help='Show only messages addressed to this participant or to "all".',
    )
    parser.add_argument("--once", action="store_true", help="Render one frame and exit.")
    args = parser.parse_args()
    if args.limit < 1:
        raise ValueError("--limit must be >= 1")
    if args.interval <= 0:
        raise ValueError("--interval must be > 0")
    args.participant = args.participant.strip()
    cache: dict[str, Any] = {
        "participants_sig": None,
        "participants": [],
        "participants_error": None,
        "messages_sig": None,
        "messages": [],
        "total_count": 0,
        "last_activity_ts": None,
        "messages_error": None,
    }
    state = load_cached_state(args, cache)
    if args.once:
        print(snapshot_frame(args, state), end="", flush=True)
        print()
        return
    width = shutil.get_terminal_size((100, 24)).columns
    print_live_header(args, state, width)
    initial_messages = state["messages"]
    if initial_messages:
        print("\n".join(render_messages(initial_messages, width)), flush=True)
    else:
        print("No messages yet.", flush=True)
    last_rendered_message_id = initial_messages[-1]["id"] if initial_messages else 0
    last_participants_sig = state["participants_sig"]
    last_messages_sig = state["messages_sig"]
    last_status_lines = live_status_lines(args, state, width)
    unchanged_polls = 0
    try:
        while True:
            width = shutil.get_terminal_size((100, 24)).columns
            state = load_cached_state(args, cache)
            changed = False
            current_status_lines = live_status_lines(args, state, width)
            if state["participants_sig"] != last_participants_sig or current_status_lines != last_status_lines:
                print("\n".join(current_status_lines), flush=True)
                last_participants_sig = state["participants_sig"]
                last_status_lines = current_status_lines
                changed = True
            if state["messages_sig"] != last_messages_sig:
                new_messages, _, _, new_messages_error = load_messages(args.limit, args.participant, since_id=last_rendered_message_id)
                last_messages_sig = state["messages_sig"]
                if new_messages_error:
                    error_line = fit(f"State | {new_messages_error}", width)
                    if error_line not in last_status_lines:
                        print(error_line, flush=True)
                        last_status_lines = [*last_status_lines, error_line]
                    changed = True
                elif new_messages:
                    print("\n".join(render_messages(new_messages, width)), flush=True)
                    last_rendered_message_id = new_messages[-1]["id"]
                    changed = True
            if changed:
                unchanged_polls = 0
            else:
                unchanged_polls += 1
            sleep_for = args.interval if changed else min(args.interval * (2 ** min(unchanged_polls, 3)), 5.0)
            time.sleep(sleep_for)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
