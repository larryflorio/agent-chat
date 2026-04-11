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


def load_messages(limit: int, participant: str) -> tuple[list[dict[str, Any]], int, str | None, str | None]:
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
                filtered.append(message)
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError, KeyError) as exc:
        return [], 0, None, f"messages.jsonl error: {exc}"
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


def frame(args: argparse.Namespace) -> str:
    width = shutil.get_terminal_size((100, 24)).columns
    participant_filter = args.participant or "none"
    participants, participants_error = load_participants()
    messages, total_count, last_activity_ts, messages_error = load_messages(args.limit, args.participant)
    state_messages: list[str] = []
    if not CHATROOM_DIR.exists():
        state_messages.append("Waiting for chatroom initialization...")
    for error in (participants_error, messages_error):
        if error:
            state_messages.append(error)
    lines = [
        "Agent Chatroom Monitor",
        fit(f"Repo: {ROOT}", width),
        f"Refresh: {args.interval:.1f}s | Participant filter: {participant_filter}",
        f"Participants: {len(participants)} | Messages: {total_count} | Last activity: {last_activity_ts or 'none'}",
        "-" * min(width, 80),
    ]
    lines.extend(fit(f"State: {message}", width) for message in state_messages)
    if state_messages:
        lines.append("-" * min(width, 80))
    lines.extend(render_participants(participants, width))
    lines.append("-" * min(width, 80))
    lines.append(f"Recent messages (showing up to {args.limit}):")
    lines.extend(render_messages(messages, width))
    lines.append("")
    lines.append("Ctrl-C to exit")
    return "\x1b[2J\x1b[H" + "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only terminal monitor for the agent chatroom.")
    parser.add_argument("--limit", type=int, default=30, help="Number of recent messages to display.")
    parser.add_argument("--interval", type=float, default=1.0, help="Refresh interval in seconds.")
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
    try:
        while True:
            print(frame(args), end="", flush=True)
            if args.once:
                print()
                return
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
