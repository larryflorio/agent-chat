# Execution-Ready Spec: Agent Chatroom MCP Server V2

## Assumed Context

This repository contains a local Python MCP server that lets multiple coding agents in the same repository coordinate through shared filesystem state.

## Objective

Implement a local MCP server in Python named `chatroom` that acts as a filesystem-backed chatroom and handoff mechanism for coding agents sharing the same git repository.

V2 changes the coordination model from one implicit room-wide stream to explicit topics:

- every message belongs to exactly one topic
- every unread cursor is tracked per participant per topic
- handoff payloads are topic-scoped
- the human viewing surface is read-only and topic-aware

The server must let agents:

- register as active participants
- leave the chatroom
- open and close explicit topics
- send directed or broadcast messages within a topic
- read recent messages from a topic
- persist per-participant, per-topic unread cursors
- write explicit topic-scoped handoff summaries
- retrieve compact resume payloads for a chosen topic
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
- All cross-process coordination must occur through files under `.chatroom_v2/`.
- No in-memory state may be relied on for correctness across processes.
- The server must behave correctly when multiple processes call tools concurrently.

## Repository-Relative State

All runtime state lives in `.chatroom_v2/` under the resolved repository root.

Repository root resolution:

- if `CHATROOM_ROOT` is set, use that path
- otherwise, use the directory containing `chatroom_mcp_server.py`

Required files:

- `.chatroom_v2/messages.jsonl`
- `.chatroom_v2/topics.json`
- `.chatroom_v2/participants.json`
- `.chatroom_v2/cursors.json`
- `.chatroom_v2/summaries.jsonl`

`.chatroom/` is legacy v1 state. V2 tools must not read from or mutate it.

### First-Use Initialization

On the first tool call in a process, the server must ensure:

- `.chatroom_v2/` exists
- `.chatroom_v2/messages.jsonl` exists
- `.chatroom_v2/summaries.jsonl` exists
- `.chatroom_v2/topics.json` exists and contains `{}`
- `.chatroom_v2/participants.json` exists and contains `{}`
- `.chatroom_v2/cursors.json` exists and contains `{}`
- `.chatroom_v2/` is present as a literal line in `.gitignore`; append it if missing

Initialization must be safe under concurrent execution.

`.gitignore` rule:

- after initialization completes, `.gitignore` must contain at least one exact line equal to `.chatroom_v2/`
- duplicate `.chatroom_v2/` lines are permitted but should be avoided
- concurrent initializers are not required to serialize `.gitignore` writes as long as they do not corrupt the file contents

## Locking Rules

Use `fcntl.flock`.

- Use `LOCK_EX` for any write to `messages.jsonl`, `topics.json`, `participants.json`, `cursors.json`, and `summaries.jsonl`
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
- viewer/export limits must follow the same cap when they are surfaced through documentation or helper tooling

Do not silently cap oversized requests. Reject them.

## Data Model

### Topic Record

`topics.json` contains a JSON object mapping topic IDs to records:

```json
{
  "parser-refactor": {
    "id": "parser-refactor",
    "title": "Parser Refactor",
    "status": "open",
    "created_by": "claude",
    "created_at": "2026-04-11T12:00:00Z",
    "closed_at": null,
    "last_activity_ts": "2026-04-11T12:00:00Z"
  }
}
```

Field rules:

- `id`: stable caller-supplied topic slug matching `^[a-z0-9][a-z0-9._-]{0,63}$`
- `title`: human-readable title shown in topic listings and viewer output
- `status`: `"open"` or `"closed"`
- `created_by`: participant name or `"system"`
- `created_at`: UTC timestamp string in the required format
- `closed_at`: UTC timestamp string or `null`
- `last_activity_ts`: UTC timestamp string reflecting the most recent activity in the topic

### Message Record

Each line in `.chatroom_v2/messages.jsonl` is one JSON object:

```json
{"id": 1, "ts": "2026-04-11T12:00:00Z", "topic_id": "parser-refactor", "from": "claude", "to": "all", "content": "Starting work"}
```

Field rules:

- `id`: positive integer, unique, monotonically increasing
- `ts`: UTC timestamp string in the required format
- `topic_id`: existing topic ID
- `from`: sender name, or `"system"` for server-generated messages
- `to`: recipient name or `"all"`
- `content`: plain-text message content

### Participant Record

`.chatroom_v2/participants.json` contains a JSON object mapping participant names to records:

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

Participant presence is still name-owned in v2. Session identity remains a later roadmap item.

### Cursor Record

`.chatroom_v2/cursors.json` contains a JSON object mapping participant names to a nested map of topic IDs to the highest message ID that participant has explicitly marked as read in that topic:

```json
{
  "claude": {
    "parser-refactor": 42
  }
}
```

Field rules:

- values must be integers `>= 0`
- missing name means cursor `0` for that participant/topic pair
- missing topic entry means cursor `0` for that participant/topic pair

### Summary Record

Each line in `.chatroom_v2/summaries.jsonl` is one JSON object:

```json
{"id": 1, "ts": "2026-04-11T12:05:00Z", "topic_id": "parser-refactor", "from": "claude", "scope": "all", "content": "Auth refactor complete; tests pending."}
```

Field rules:

- `id`: positive integer, unique, monotonically increasing within `summaries.jsonl`
- `ts`: UTC timestamp string in the required format
- `topic_id`: existing topic ID
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
- A `join` for an existing name not already joined by the current process must be rejected
- A rejoin preserves `joined_at` if the name is already active

The process must register a best-effort `atexit` handler that calls `leave(name)` for each participant name joined by that process.

This is best-effort only. The implementation is not required to detect hard crashes or force-killed processes. A stale participant record left behind by a crashed process may block reuse of that name until it is manually removed or explicitly left by another tool call.

## Input Normalization

The following inputs must be stripped of leading and trailing whitespace before validation, comparison, storage, or message generation:

- `join.name`
- `join.role`
- `leave.name`
- `open_topic.topic_id`
- `open_topic.title`
- `close_topic.topic_id`
- `list_topics.name`
- `list_topics.status`
- `send_message.name`
- `send_message.topic_id`
- `send_message.content`
- `send_message.to`
- `read_messages.topic_id`
- `read_messages.participant`
- `get_cursor.name`
- `get_cursor.topic_id`
- `set_cursor.name`
- `set_cursor.topic_id`
- `read_unread.name`
- `read_unread.topic_id`
- `write_summary.name`
- `write_summary.topic_id`
- `write_summary.content`
- `write_summary.scope`
- `read_latest_summary.topic_id`
- `read_latest_summary.scope`
- `get_handoff.name`
- `get_handoff.topic_id`

Values after stripping are canonical.

## Tools

Expose exactly these MCP tools:

- `join`
- `leave`
- `open_topic`
- `close_topic`
- `list_topics`
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
4. if the name is already present and was not previously joined by the current process, reject the join
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
5. return `{"left": true}` if removed, otherwise `{"left": false}`

`leave` must not write a system message. V2 does not rely on a room-wide log for presence transitions.

### `open_topic`

Parameters:

- `topic_id: str`
- `title: str`

Behavior:

1. ensure state exists
2. validate non-blank `topic_id` and `title`
3. validate `topic_id` as a stable slug matching `^[a-z0-9][a-z0-9._-]{0,63}$`
4. acquire `LOCK_EX` on `topics.json`
5. reject if `topic_id` already exists
6. create the topic record with `status="open"`, `closed_at=null`, and `last_activity_ts` set to now
7. release lock
8. return the topic record

### `close_topic`

Parameters:

- `topic_id: str`

Behavior:

1. ensure state exists
2. validate non-blank `topic_id`
3. acquire `LOCK_EX` on `topics.json`
4. reject unknown topic IDs
5. mark the topic closed if it is open
6. if the topic is already closed, return `{"closed": false}`
7. if the topic is newly closed, set `closed_at`, update `last_activity_ts`, and return `{"closed": true}`

Closed topics remain readable, but message and summary writes must reject them.

### `list_topics`

Parameters:

- `name: str = ""`
- `status: str = "open"`

Behavior:

1. ensure state exists
2. normalize `name` and `status`
3. accept `status` values `"open"`, `"closed"`, and `"all"`
4. reject unknown status filters
5. read topics under `LOCK_SH`
6. sort by `last_activity_ts` descending, then `id`
7. if `name` is supplied, include per-topic unread metadata for that participant

Return shape:

- list of topic records containing at least `id`, `title`, `status`, `created_by`, `created_at`, `closed_at`, `last_activity_ts`
- when `name` is supplied, each topic record also includes:
  - `cursor`
  - `unread_count`
  - `latest_summary`
  - `latest_message_id`

### `send_message`

Parameters:

- `name: str`
- `topic_id: str`
- `content: str`
- `to: str = "all"`

Behavior:

1. ensure state exists
2. validate non-blank `name`, `topic_id`, `content`, and `to`
3. validate that `topic_id` exists and is open
4. append one message record to `messages.jsonl`
5. update the topic's `last_activity_ts`
6. return the assigned message ID

Return shape:

- `{"id": <int>}`

`send_message` does not require the sender to be active in `participants.json`.

### `read_messages`

Parameters:

- `topic_id: str`
- `since_id: int = 0`
- `limit: int = 50`
- `participant: str = ""`

Behavior:

1. ensure state exists
2. validate `topic_id`
3. reject unknown topic IDs
4. validate `since_id >= 0`
5. validate `1 <= limit <= 100`
6. read `messages.jsonl` under `LOCK_SH`
7. keep messages for the requested topic with `id > since_id`
8. if `participant` is non-empty, keep only messages where `to` is `"all"` or exactly equals `participant`
9. apply recipient filtering before `limit`
10. return at most `limit` messages in ascending `id` order

Return shape:

- list of dicts containing exactly `id`, `ts`, `topic_id`, `from`, `to`, `content`

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
  "topic_count": 1,
  "open_topic_count": 1,
  "message_count": 3,
  "summary_count": 1,
  "last_activity_ts": "2026-04-11T12:00:10Z"
}
```

Field semantics:

- `participant_count`: count of active participants
- `topic_count`: count of known topics
- `open_topic_count`: count of topics with `status="open"`
- `message_count`: count of lines in `messages.jsonl`
- `summary_count`: count of lines in `summaries.jsonl`
- `last_activity_ts`: timestamp of the most recent topic activity; `null` if no topics exist

`get_status` is not required to return an atomic cross-file snapshot.

### `get_cursor`

Parameters:

- `name: str`
- `topic_id: str`

Return shape:

```json
{"name": "claude", "topic_id": "parser-refactor", "last_read_id": 42}
```

Behavior:

1. ensure state exists
2. validate `name` and `topic_id`
3. reject unknown topic IDs
4. read the participant/topic cursor under `LOCK_SH`
5. missing cursor state must be reported as `0`

### `set_cursor`

Parameters:

- `name: str`
- `topic_id: str`
- `message_id: int`

Behavior:

1. ensure state exists
2. validate `message_id >= 0`
3. validate `topic_id`
4. reject unknown topic IDs
5. reject `message_id` values greater than the current latest message ID in that topic
6. write the cursor under `LOCK_EX`
7. never move the stored cursor backwards; the stored value becomes `max(existing_cursor, message_id)`

Return shape:

```json
{"name": "claude", "topic_id": "parser-refactor", "last_read_id": 42}
```

### `read_unread`

Parameters:

- `name: str`
- `topic_id: str`
- `limit: int = 50`
- `mark_read: bool = true`

Behavior:

1. ensure state exists
2. validate `name` and `topic_id`
3. reject unknown topic IDs
4. read the participant/topic cursor; missing cursor means `0`
5. read messages visible to that participant in that topic with `id > cursor`
6. apply participant filtering before `limit`
7. if `mark_read` is true and at least one message is returned, advance the cursor to the highest returned message ID
8. cursor updates performed by this tool must also be monotonic

Return shape:

```json
{
  "name": "claude",
  "topic_id": "parser-refactor",
  "last_read_id": 42,
  "messages": []
}
```

The returned `last_read_id` is the post-operation cursor value for that topic.

### `write_summary`

Parameters:

- `name: str`
- `topic_id: str`
- `content: str`
- `scope: str = "all"`

Behavior:

1. ensure state exists
2. validate non-blank `name`, `topic_id`, `content`, and `scope`
3. validate that `topic_id` exists and is open
4. append a summary record to `summaries.jsonl`
5. update the topic's `last_activity_ts`
6. return the assigned summary ID

Return shape:

```json
{"id": 3}
```

### `read_latest_summary`

Parameters:

- `topic_id: str`
- `scope: str = "all"`

Behavior:

1. ensure state exists
2. validate `topic_id`
3. reject unknown topic IDs
4. read `summaries.jsonl` under `LOCK_SH`
5. return the most recent summary whose `topic_id` and `scope` exactly match the request

Return shape:

- summary dict with `id`, `ts`, `topic_id`, `from`, `scope`, `content`
- `null` if no matching summary exists

### `get_handoff`

Parameters:

- `name: str`
- `topic_id: str`
- `recent_limit: int = 10`

Behavior:

1. ensure state exists
2. validate `name`, `topic_id`, and `1 <= recent_limit <= 100`
3. reject unknown topic IDs
4. return a compact orientation payload for a new or resumed session in that topic

Return shape:

```json
{
  "participants": [],
  "topic": {},
  "latest_message_id": 42,
  "cursor": 40,
  "unread_count": 2,
  "latest_summary": null,
  "recent_messages": []
}
```

Field semantics:

- `participants`: active participants sorted by `name`
- `topic`: the topic record for `topic_id`
- `latest_message_id`: latest message ID in that topic, or `0` if empty
- `cursor`: current cursor for the participant/topic pair
- `unread_count`: number of messages visible to `name` in that topic with `id > cursor`
- `latest_summary`: the most recent summary whose `topic_id` matches and whose `scope` is `"all"` or exactly equals `name`
- `recent_messages`: the most recent visible messages for that topic, returned in ascending `id` order, limited by `recent_limit`

This tool is the preferred low-context resume path for agents starting a new session or returning to a known topic.

## Read-Only Viewer And Export Surface

The repository includes a read-only terminal viewer, `chatroom_monitor.py`, for humans and scripts that need to inspect chat state without mutating it.

Viewer requirements:

- it must not write to any chatroom state file
- overview mode without a topic must show topics, not a mixed room-wide message tail
- topic mode must show one topic at a time
- topic-aware output must use the same `.chatroom_v2/` state as the MCP server
- `--format json` is the structured export surface for tooling and wrappers

Recommended viewer behavior:

- overview mode shows open topics, last activity, latest summary snippets, and participant presence
- topic mode shows the chosen topic metadata, latest summary, and recent messages
- `--participant <name>` narrows the visible message set within the selected topic or topic overview
- `--unread-only` is an overview convenience that filters the topic list to entries with unread messages for that participant
- `--latest-topic` is a navigation convenience that may resolve the most relevant topic for that participant before rendering topic mode
- these conveniences do not change the underlying contract: overview mode remains topic-oriented, topic mode remains one-topic-at-a-time, and the viewer remains read-only

## Error Handling

Use ordinary Python exceptions for invalid input or unrecoverable file corruption.

Minimum validation requirements:

- reject blank required string inputs after normalization
- reject negative `since_id`
- reject `limit` or `recent_limit` outside `1..100`
- reject negative cursor values
- reject `set_cursor.message_id` values above the current latest message ID for that topic
- reject unknown topic IDs where the tool requires an existing topic
- reject writes to closed topics

Do not silently coerce invalid values.

## Serialization Rules

- Use JSON for `participants.json`, `cursors.json`, and `topics.json`
- Use JSON Lines for `messages.jsonl` and `summaries.jsonl`
- Encode files as UTF-8
- Keep `messages.jsonl` and `summaries.jsonl` append-only

## Deliberate Non-Goal

Physical log rotation is not part of this version.

Reason:

- message IDs are defined as `line_count + 1` inside the locked append path
- rotating the live message log would change line count semantics and requires a different storage contract

Context-window control in this version is provided by explicit topics, per-topic cursors, per-topic summaries, handoff payloads, hard read caps, and the read-only viewer/export surface instead of message archival.
