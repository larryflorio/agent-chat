# Execution-Ready Spec: Agent Chatroom MCP Server

## Assumed Context

This repository contains a local Python MCP server that lets multiple coding agents in the same repository coordinate through shared filesystem state.

## Objective

Implement a local MCP server in Python named `chatroom` that acts as a filesystem-backed chatroom and handoff mechanism for coding agents sharing the same git repository.

The server must let agents:

- register as active participants
- leave the chatroom
- send directed or broadcast messages
- read recent messages
- persist per-participant unread cursors
- write explicit handoff summaries
- retrieve a compact resume payload for new sessions
- inspect active participants and aggregate status

The server is local-only. It is not a network service.

## Required Output

Produce the MCP server runtime in the repository root as:

- `chatroom_mcp_server.py`

Other repository files such as documentation, tests, and optional read-only helper tooling may exist, but the MCP server runtime itself must remain single-file.

## Technology Constraints

- Language: Python 3
- Dependencies: Python standard library plus `mcp`
- MCP API: `FastMCP` from `mcp.server.fastmcp`
- Transport: stdio
- Implementation shape: single file

## Runtime Model

- Each MCP client connection runs its own server process.
- Multiple server processes may run concurrently in the same repository.
- All cross-process coordination must occur through files under `.chatroom/`.
- No in-memory state may be relied on for correctness across processes.
- The server must behave correctly when multiple processes call tools concurrently.

## Repository-Relative State

All runtime state lives in `.chatroom/` under the resolved repository root.

Repository root resolution:

- if `CHATROOM_ROOT` is set, use that path
- otherwise, use the directory containing `chatroom_mcp_server.py`

Required files:

- `.chatroom/messages.jsonl`
- `.chatroom/participants.json`
- `.chatroom/cursors.json`
- `.chatroom/summaries.jsonl`

### First-Use Initialization

On the first tool call in a process, the server must ensure:

- `.chatroom/` exists
- `.chatroom/messages.jsonl` exists
- `.chatroom/summaries.jsonl` exists
- `.chatroom/participants.json` exists and contains `{}`
- `.chatroom/cursors.json` exists and contains `{}`
- `.chatroom/` is present as a literal line in `.gitignore`; append it if missing

Initialization must be safe under concurrent execution.

`.gitignore` rule:

- after initialization completes, `.gitignore` must contain at least one exact line equal to `.chatroom/`
- duplicate `.chatroom/` lines are permitted but should be avoided
- concurrent initializers are not required to serialize `.gitignore` writes as long as they do not corrupt the file contents

## Locking Rules

Use `fcntl.flock`.

- Use `LOCK_EX` for any write to `messages.jsonl`, `participants.json`, `cursors.json`, and `summaries.jsonl`
- Use `LOCK_SH` for any read of those files

Lock scope must include the full read-modify-write sequence for writes.

## Timestamp Rules

All timestamps must be emitted in UTC using this exact format:

- `YYYY-MM-DDTHH:MM:SSZ`

Use second precision only. No fractional seconds. No local offsets.

## Hard Read Limit

The server must enforce a maximum read limit of `100` messages for any read-oriented tool.

- `read_messages.limit` must be `>= 1` and `<= 100`
- `read_unread.limit` must be `>= 1` and `<= 100`
- `get_handoff.recent_limit` must be `>= 1` and `<= 100`

Do not silently cap oversized requests. Reject them.

## Data Model

### Message Record

Each line in `.chatroom/messages.jsonl` is one JSON object:

```json
{"id": 1, "ts": "2026-04-11T12:00:00Z", "from": "claude", "to": "all", "content": "Starting work"}
```

Field rules:

- `id`: positive integer, unique, monotonically increasing
- `ts`: UTC timestamp string in the required format
- `from`: sender name, or `"system"` for server-generated messages
- `to`: recipient name or `"all"`
- `content`: plain-text message content

### Participant Record

`.chatroom/participants.json` contains a JSON object mapping participant names to records:

```json
{
  "claude": {
    "name": "claude",
    "role": "general",
    "joined_at": "2026-04-11T12:00:00Z",
    "last_seen": "2026-04-11T12:00:00Z"
  }
}
```

### Cursor Record

`.chatroom/cursors.json` contains a JSON object mapping participant names to the highest message ID that participant has explicitly marked as read:

```json
{
  "claude": 42
}
```

Field rules:

- values must be integers `>= 0`
- missing name means cursor `0`

### Summary Record

Each line in `.chatroom/summaries.jsonl` is one JSON object:

```json
{"id": 1, "ts": "2026-04-11T12:05:00Z", "from": "claude", "scope": "all", "content": "Auth refactor complete; tests pending."}
```

Field rules:

- `id`: positive integer, unique, monotonically increasing within `summaries.jsonl`
- `ts`: UTC timestamp string in the required format
- `from`: sender name
- `scope`: `"all"` or a participant name
- `content`: plain-text summary content

## ID Allocation

Message IDs must be assigned while holding `LOCK_EX` on `messages.jsonl`.

Summary IDs must be assigned while holding `LOCK_EX` on `summaries.jsonl`.

Allocation algorithm for both append-only logs:

1. count existing lines in the target file
2. set `id = line_count + 1`
3. append the new record as one JSON line
4. flush before unlocking

No alternative ID scheme is permitted in this version.

## Participant Lifecycle

Participant identity is the stripped `name` string supplied to tools.

- A `join` for a new name creates a participant record
- A `join` for an existing name from the same process updates `role` and `last_seen`
- A `join` for an existing name from a different process must be rejected
- A rejoin preserves `joined_at` if the name is already active

The process must register a best-effort `atexit` handler that calls `leave(name)` for each participant name joined by that process.

This is best-effort only. The implementation is not required to detect hard crashes or force-killed processes.

## Input Normalization

The following inputs must be stripped of leading and trailing whitespace before validation, comparison, storage, or message generation:

- `join.name`
- `join.role`
- `leave.name`
- `send_message.name`
- `send_message.content`
- `send_message.to`
- `get_cursor.name`
- `set_cursor.name`
- `read_unread.name`
- `write_summary.name`
- `write_summary.content`
- `write_summary.scope`
- `read_latest_summary.scope`
- `get_handoff.name`

Values after stripping are canonical.

## Tools

Expose exactly these MCP tools:

- `join`
- `leave`
- `send_message`
- `read_messages`
- `list_participants`
- `get_status`
- `get_cursor`
- `set_cursor`
- `read_unread`
- `write_summary`
- `read_latest_summary`
- `get_handoff`

### `join`

Parameters:

- `name: str`
- `role: str = "general"`

Behavior:

1. ensure state exists
2. acquire `LOCK_EX` on `participants.json`
3. create or update the participant record
4. if the name is already active in a different process, reject the join
5. release lock
6. register a best-effort `atexit` leave handler for `name` in the current process
7. return the full participant list sorted by `name`

`join` must not write a system message.

### `leave`

Parameters:

- `name: str`

Behavior:

1. ensure state exists
2. acquire `LOCK_EX` on `participants.json`
3. remove the participant if present
4. release lock
5. if a participant was removed, append a system message to `messages.jsonl` with content `"<name> left the chatroom"`

Return shape:

- `{"left": true}` if removed
- `{"left": false}` if not present

`leave` is not required to be linearizable across both files.

### `send_message`

Parameters:

- `name: str`
- `content: str`
- `to: str = "all"`

Behavior:

1. ensure state exists
2. validate non-blank `name`, `content`, and `to`
3. append one message record to `messages.jsonl`
4. return the assigned message ID

Return shape:

- `{"id": <int>}`

`send_message` does not require the sender to be active in `participants.json`.

### `read_messages`

Parameters:

- `since_id: int = 0`
- `limit: int = 50`
- `participant: str = ""`

Behavior:

1. ensure state exists
2. validate `since_id >= 0`
3. validate `1 <= limit <= 100`
4. read `messages.jsonl` under `LOCK_SH`
5. keep messages with `id > since_id`
6. if `participant` is non-empty, keep only messages where `to` is `"all"` or exactly equals `participant`
7. apply recipient filtering before `limit`
8. return at most `limit` messages in ascending `id` order

Return shape:

- list of dicts containing exactly `id`, `ts`, `from`, `to`, `content`

### `list_participants`

Parameters:

- none

Behavior:

1. ensure state exists
2. read `participants.json` under `LOCK_SH`
3. return participant records sorted by `name`

### `get_status`

Parameters:

- none

Return shape:

```json
{
  "participant_count": 1,
  "message_count": 3,
  "last_activity_ts": "2026-04-11T12:00:10Z"
}
```

Field semantics:

- `participant_count`: count of active participants
- `message_count`: count of lines in `messages.jsonl`
- `last_activity_ts`: timestamp of the most recent message in `messages.jsonl`; `null` if no messages exist

`get_status` is not required to return an atomic cross-file snapshot.

### `get_cursor`

Parameters:

- `name: str`

Return shape:

```json
{"name": "claude", "last_read_id": 42}
```

Missing cursor state must be reported as `0`.

### `set_cursor`

Parameters:

- `name: str`
- `message_id: int`

Behavior:

1. ensure state exists
2. validate `message_id >= 0`
3. reject `message_id` values greater than the current latest message ID
4. write the cursor under `LOCK_EX`
5. never move the stored cursor backwards; the stored value becomes `max(existing_cursor, message_id)`

Return shape:

```json
{"name": "claude", "last_read_id": 42}
```

### `read_unread`

Parameters:

- `name: str`
- `limit: int = 50`
- `mark_read: bool = true`

Behavior:

1. ensure state exists
2. read the participant cursor; missing cursor means `0`
3. read messages visible to that participant with `id > cursor`
4. apply participant filtering before `limit`
5. if `mark_read` is true and at least one message is returned, advance the cursor to the highest returned message ID
6. cursor updates performed by this tool must also be monotonic

Return shape:

```json
{
  "name": "claude",
  "last_read_id": 42,
  "messages": []
}
```

The returned `last_read_id` is the post-operation cursor value.

### `write_summary`

Parameters:

- `name: str`
- `content: str`
- `scope: str = "all"`

Behavior:

1. ensure state exists
2. validate non-blank `name`, `content`, and `scope`
3. append a summary record to `summaries.jsonl`
4. return the assigned summary ID

Return shape:

```json
{"id": 3}
```

### `read_latest_summary`

Parameters:

- `scope: str = "all"`

Behavior:

1. ensure state exists
2. read `summaries.jsonl` under `LOCK_SH`
3. return the most recent summary whose `scope` exactly matches the requested scope

Return shape:

- summary dict with `id`, `ts`, `from`, `scope`, `content`
- `null` if no matching summary exists

### `get_handoff`

Parameters:

- `name: str = ""`
- `recent_limit: int = 10`

Behavior:

1. ensure state exists
2. validate `1 <= recent_limit <= 100`
3. return a compact orientation payload for a new or resumed session

Return shape:

```json
{
  "participants": [],
  "latest_message_id": 42,
  "cursor": 40,
  "unread_count": 2,
  "latest_summary": null,
  "recent_messages": []
}
```

Field semantics:

- `participants`: active participants sorted by `name`
- `latest_message_id`: latest message ID in `messages.jsonl`, or `0` if empty
- `cursor`: current cursor for `name`, or `null` if `name` is blank
- `unread_count`: number of messages visible to `name` with `id > cursor`, or `null` if `name` is blank
- `latest_summary`: the most recent summary whose `scope` is `"all"` or exactly equals `name`; if `name` is blank, only scope `"all"` is eligible
- `recent_messages`: the most recent visible messages, returned in ascending `id` order, limited by `recent_limit`

This tool is the preferred low-context resume path for agents starting a new session.

## Error Handling

Use ordinary Python exceptions for invalid input or unrecoverable file corruption.

Minimum validation requirements:

- reject blank required string inputs after normalization
- reject negative `since_id`
- reject `limit` or `recent_limit` outside `1..100`
- reject negative cursor values
- reject `set_cursor.message_id` values above the current latest message ID

Do not silently coerce invalid values.

## Serialization Rules

- Use JSON for `participants.json` and `cursors.json`
- Use JSON Lines for `messages.jsonl` and `summaries.jsonl`
- Encode files as UTF-8
- Keep `messages.jsonl` and `summaries.jsonl` append-only

## Deliberate Non-Goal

Physical log rotation is not part of this version.

Reason:

- message IDs are defined as `line_count + 1` inside the locked append path
- rotating the live message log would change line count semantics and requires a different storage contract

Context-window control in this version is provided by cursors, summaries, handoff payloads, and hard read caps instead of message archival.
