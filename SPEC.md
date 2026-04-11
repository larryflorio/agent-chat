# Execution-Ready Spec: Agent Chatroom MCP Server

## Assumed Context

This document is the implementation spec for a local Python MCP server that allows multiple coding agents in the same repository to exchange messages through shared filesystem state.

## Objective

Implement a local MCP server in Python named `chatroom` that acts as a filesystem-backed chatroom and message broker for coding agents sharing the same git repository.

The server must allow agents to:

- register themselves as active participants
- leave the chatroom
- send directed or broadcast messages
- read messages addressed to them or to everyone
- inspect active participants
- inspect aggregate status

The server is local-only. It is not a network service.

## Required Output

Produce exactly one runtime file in the repository root:

- `chatroom_mcp_server.py`

Do not create a README, test suite, package metadata, or helper modules.

## Technology Constraints

- Language: Python 3
- Dependencies: Python standard library plus `mcp`
- MCP API: `FastMCP` from `mcp.server.fastmcp`
- Transport: stdio
- Implementation shape: single file
- Target size: under 300 lines, excluding blank lines and top-of-file config comments

## Runtime Model

- Each MCP client connection runs its own server process.
- Multiple server processes may run concurrently in the same repository.
- All cross-process coordination must occur through files under `.chatroom/`.
- No in-memory state may be relied on for correctness across processes.
- The server must behave correctly when multiple processes call tools concurrently.

## Repository-Relative State

All runtime state lives in `.chatroom/` at the current working directory where the server process is launched.

Required files:

- `.chatroom/messages.jsonl`
- `.chatroom/participants.json`

### First-Use Initialization

On the first tool call in a process, the server must ensure:

- `.chatroom/` exists
- `.chatroom/messages.jsonl` exists
- `.chatroom/participants.json` exists and contains `{}` if newly created
- `.chatroom/` is present as a literal line in `.gitignore`; append it if missing

Initialization must be safe under concurrent execution.

`.gitignore` rule:

- after initialization completes, `.gitignore` must contain at least one exact line equal to `.chatroom/`
- duplicate `.chatroom/` lines are permitted but should be avoided
- concurrent initializers are not required to serialize `.gitignore` writes as long as they do not corrupt the file contents

## Locking Rules

Use `fcntl.flock`.

- Use `LOCK_EX` for any write to `messages.jsonl`
- Use `LOCK_EX` for any write to `participants.json`
- Use `LOCK_SH` for any read of `messages.jsonl`
- Use `LOCK_SH` for any read of `participants.json`

Lock scope must include the full read-modify-write sequence for writes.

## Timestamp Rules

All timestamps must be emitted in UTC using this exact format:

- `YYYY-MM-DDTHH:MM:SSZ`

Use second precision only. No fractional seconds. No local offsets.

## Data Model

### Message Record

Each line in `.chatroom/messages.jsonl` is one JSON object with this schema:

```json
{"id": 1, "ts": "2026-04-11T12:00:00Z", "from": "claude", "to": "all", "content": "Starting work"}
```

Field rules:

- `id`: positive integer, unique, monotonically increasing
- `ts`: UTC timestamp string in the required format
- `from`: sender name, or `"system"` for server-generated messages
- `to`: recipient name or `"all"`
- `content`: plain-text message content

### Participants File

`.chatroom/participants.json` must contain a single JSON object mapping participant names to records:

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

Field rules:

- `name`: participant name; must equal the top-level key
- `role`: caller-provided role string
- `joined_at`: timestamp when the participant name first registered in the current active session entry
- `last_seen`: most recent successful `join` by that name

## Message ID Allocation

Message IDs must be assigned while holding `LOCK_EX` on `messages.jsonl`.

Allocation algorithm:

1. count existing lines in `messages.jsonl`
2. set `id = line_count + 1`
3. append the new message as one JSON line
4. flush before unlocking

No alternative ID scheme is permitted.

## Participant Lifecycle

### Registration Semantics

Participant identity is the `name` string supplied to tools.

- A `join` for a new name creates a participant record
- A `join` for an existing name updates `role` and `last_seen`
- A rejoin must preserve the existing `joined_at` if the name is already active

### Exit Cleanup

The process must register a best-effort `atexit` handler that calls `leave(name)` for each participant name joined by that process.

This is best-effort only. The implementation is not required to detect hard crashes or force-killed processes.

Do not implement heartbeat, TTL expiry, or background cleanup.

## Tools

Expose exactly these MCP tools:

- `join`
- `leave`
- `send_message`
- `read_messages`
- `list_participants`
- `get_status`

No additional tools.

### `join`

Parameters:

- `name: str`
- `role: str = "general"`

Behavior:

1. ensure state exists
2. acquire `LOCK_EX` on `participants.json`
3. create or update the participant record
4. release lock
5. register a best-effort `atexit` leave handler for `name` in the current process
6. return the full current participant list

Return shape:

- list of participant dicts
- each dict must contain `name`, `role`, `joined_at`, `last_seen`
- order must be ascending by `name`

Side effects:

- `join` must not write a system message

### `leave`

Parameters:

- `name: str`

Behavior:

1. ensure state exists
2. acquire `LOCK_EX` on `participants.json`
3. remove the participant if present
4. release lock
5. if a participant was removed, append a system message to `messages.jsonl` saying `"<name> left the chatroom"`
6. if the name was not present, do nothing else

Return shape:

- `{"left": true}` if removed
- `{"left": false}` if not present

System message rules:

- `from = "system"`
- `to = "all"`
- `content = "<name> left the chatroom"`

Ordering note:

- `leave` is not required to be linearizable across both files
- if a same-name `join` occurs after participant removal but before the system message append, the `"left the chatroom"` message is still valid and must still be written
- do not attempt cross-file transactional semantics

### `send_message`

Parameters:

- `name: str`
- `content: str`
- `to: str = "all"`

Behavior:

1. ensure state exists
2. append one message record to `messages.jsonl`
3. return the assigned message ID

Validation:

- `name` must be non-empty after stripping whitespace
- `content` must be non-empty after stripping whitespace
- `to` must be non-empty after stripping whitespace

Normalization:

- `name`, `content`, and `to` must be stripped of leading and trailing whitespace before validation and before storage

Return shape:

- `{"id": <int>}`

Notes:

- `send_message` does not require the sender to be present in `participants.json`

### `read_messages`

Parameters:

- `since_id: int = 0`
- `limit: int = 50`
- `participant: str = ""`

Behavior:

1. ensure state exists
2. acquire `LOCK_SH` on `messages.jsonl`
3. read messages with `id > since_id`
4. if `participant` is non-empty, keep only messages where `to` is `"all"` or exactly equals `participant`
5. return at most `limit` messages in ascending `id` order

Return shape:

- list of dicts containing exactly `id`, `ts`, `from`, `to`, `content`

Filtering rule:

- apply recipient filtering before `limit`

Validation:

- `since_id` must be `>= 0`
- `limit` must be `>= 1`

### `list_participants`

Parameters:

- none

Behavior:

1. ensure state exists
2. acquire `LOCK_SH` on `participants.json`
3. return all active participants

Return shape:

- list of participant dicts
- each dict must contain `name`, `role`, `joined_at`, `last_seen`
- order must be ascending by `name`

### `get_status`

Parameters:

- none

Behavior:

1. ensure state exists
2. read `participants.json` under `LOCK_SH`
3. read `messages.jsonl` under `LOCK_SH`
4. return aggregate status

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

Participant updates do not count as activity for `last_activity_ts`.

Snapshot rule:

- `get_status` is not required to return an atomic cross-file snapshot
- values may reflect slightly different instants because `participants.json` and `messages.jsonl` are read under separate locks

## Error Handling

Use ordinary Python exceptions for invalid input or unrecoverable file corruption.

Minimum validation requirements:

- reject blank `name` in `join`, `leave`, and `send_message`
- reject blank `content` in `send_message`
- reject blank `to` in `send_message`
- reject negative `since_id`
- reject non-positive `limit`

Do not silently coerce invalid values.

Input normalization rule:

- `join.name`, `join.role`, `leave.name`, `send_message.name`, `send_message.content`, and `send_message.to` must be stripped of leading and trailing whitespace before any validation, comparison, storage, or message generation
- values after stripping are the canonical values used everywhere in the implementation

## Serialization Rules

- Use JSON for `participants.json`
- Use JSON Lines for `messages.jsonl`
- Encode files as UTF-8
- One message object per line in `messages.jsonl`
- Preserve append-only behavior for `messages.jsonl`

## Configuration Comments

The generated `chatroom_mcp_server.py` file must include these configuration examples as comments at the top of the file.

Claude Code:

```json
{
  "mcpServers": {
    "chatroom": {
      "command": "python3",
      "args": ["chatroom_mcp_server.py"]
    }
  }
}
```

Codex CLI:

```toml
[mcp_servers.chatroom]
command = "python3"
args = ["chatroom_mcp_server.py"]
```

## Acceptance Criteria

An implementation satisfies this spec only if all of the following are true:

- it runs as a FastMCP stdio server named `chatroom`
- it exposes exactly the six required tools
- it creates `.chatroom/` and required files lazily on first tool use
- it uses `fcntl.flock` with the required lock modes
- message IDs are unique and sequential under concurrent writers
- `messages.jsonl` remains append-only
- `join` returns current participants and does not emit a system message
- `leave` removes active participants and emits exactly one system message when removal occurs
- `read_messages` filters before limiting
- `get_status.last_activity_ts` is derived from the most recent message only
- the implementation stays within the dependency, file-count, and single-file constraints
