# Agent Chatroom MCP Server

Local MCP server for letting multiple coding agents in the same repository coordinate through a shared chat log.

It is a small stdio server written in Python. Each client runs its own process. Shared state lives on disk in `.chatroom/`, so agents can discover each other, send direct or broadcast messages, and read the conversation history.

## Quick Start

1. Install the only dependency:

```bash
python3 -m pip install mcp
```

2. Configure your MCP client to launch `chatroom_mcp_server.py`.
   See [Configure Claude Code](#configure-claude-code) or [Configure Codex CLI](#configure-codex-cli).

3. Start your agents in the same repository.

4. Have each agent call `join` with a unique stable name such as `claude` or `codex`.

5. On resumed sessions, call `get_handoff(name=...)` before replaying chat history.

## Rules Of The Road

- Live participant names are exclusive. If one running process has joined as `codex`, a second running process cannot also join as `codex`.
- Process-exit cleanup is best-effort. Hard-killed agents can leave stale participants behind.
- By default, the server and monitor resolve the chatroom root from the directory containing their script files. If your client launches elsewhere, use an absolute path for `chatroom_mcp_server.py` or set `CHATROOM_ROOT=/absolute/path/to/repo`.

## What It Does

- registers active participants
- sends broadcast messages to `all`
- sends direct messages to a named participant
- reads messages after a given message ID
- tracks per-participant unread cursors
- stores explicit handoff summaries
- returns compact handoff state for resumed sessions
- lists active participants
- reports basic chatroom status

This is local-only. No network transport, auth, or encryption.

## Requirements

- Python 3
- `mcp` Python package

## Files

Runtime state is created lazily on first use:

- `.chatroom/messages.jsonl`
- `.chatroom/participants.json`
- `.chatroom/cursors.json`
- `.chatroom/summaries.jsonl`

The server also adds `.chatroom/` to `.gitignore` if it is not already present.

## Agent Instructions

Shared repository guidance lives in `AGENTS.md`.

If you want private, operator-specific agent instructions, copy `AGENTS.local.example` to `AGENTS.local.md`. That local file is gitignored and should not contain secrets.

## Configuration

### Configure Claude Code

Add this to `.claude/settings.json`:

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

### Configure Codex CLI

Add this to `.codex/config.toml`:

```toml
[mcp_servers.chatroom]
command = "python3"
args = ["chatroom_mcp_server.py"]
```

### Server Entrypoint

For direct debugging from the repository root:

```bash
python3 chatroom_mcp_server.py
```

The server uses stdio transport, so you normally do not run it by hand for long. Your MCP client should launch it as a subprocess.

## Monitor / Debugging

### Terminal Monitor

Run the read-only terminal monitor from the repository root:

```bash
python3 chatroom_monitor.py
```

Useful options:

```bash
python3 chatroom_monitor.py --limit 50
python3 chatroom_monitor.py --participant codex
python3 chatroom_monitor.py --interval 0.5
python3 chatroom_monitor.py --once
```

The monitor reads `.chatroom/messages.jsonl` and `.chatroom/participants.json` under shared locks and redraws the terminal in place. It does not modify chatroom state.

### Quick Check

Syntax check:

```bash
python3 -m py_compile chatroom_mcp_server.py chatroom_monitor.py
```

Regression tests:

```bash
python3 -m pytest -q
```

Manual run check:

```bash
python3 -c "import chatroom_mcp_server as s; print(s.join('alice')); print(s.send_message('alice', 'hello')); print(s.read_unread('alice')); print(s.write_summary('alice', 'Initial handoff')); print(s.get_handoff('alice')); print(s.leave('alice'))"
```

## Available Tools

### `join`

Registers an agent as active.

Parameters:

- `name: str`
- `role: str = "general"`

Returns the current participant list.

### `leave`

Removes an active participant and writes a system message like `"alice left the chatroom"`.

Parameters:

- `name: str`

Returns:

```json
{"left": true}
```

### `send_message`

Appends a message to the shared log.

Parameters:

- `name: str`
- `content: str`
- `to: str = "all"`

Returns:

```json
{"id": 12}
```

### `read_messages`

Reads messages with `id > since_id`. If `participant` is set, only messages addressed to that participant or to `all` are returned.

Parameters:

- `since_id: int = 0`
- `limit: int = 50`
- `participant: str = ""`

The server rejects `limit` values above `100`.

### `list_participants`

Returns all active participants.

### `get_status`

Returns:

```json
{
  "participant_count": 2,
  "message_count": 14,
  "last_activity_ts": "2026-04-11T13:00:00Z"
}
```

### `get_cursor`

Returns the stored unread cursor for a participant.

Example:

```json
{"name": "codex", "last_read_id": 12}
```

### `set_cursor`

Sets the unread cursor for a participant to a specific message ID.

Cursor updates are monotonic: the stored cursor never moves backwards.

### `read_unread`

Reads messages visible to a participant after that participant's cursor.

Parameters:

- `name: str`
- `limit: int = 50`
- `mark_read: bool = true`

If `mark_read` is true, the cursor advances to the highest returned message ID and never regresses.

### `write_summary`

Appends a summary record intended for cross-session handoff.

Parameters:

- `name: str`
- `content: str`
- `scope: str = "all"`

### `read_latest_summary`

Returns the latest summary for an exact scope.

### `get_handoff`

Returns the preferred compact orientation payload for a new or resumed session:

- active participants
- latest message ID
- current cursor for a named participant
- unread count for that participant
- latest relevant summary
- recent visible messages

## Typical Agent Flow

1. Agent starts and calls `join`.
2. On a resumed session, the agent calls `get_handoff(name=...)`.
3. The agent reads the latest summary or uses `read_unread(name=...)` instead of replaying the full log.
4. The agent sends status updates with `send_message`.
5. The agent writes a summary with `write_summary` when handing work off across sessions.
6. The agent calls `leave` when done.

## Operational Notes

- Message IDs are assigned under an exclusive file lock, so concurrent writers still get unique sequential IDs.
- Cursor writes are monotonic, so stale callers cannot move unread state backwards.
- Participant names are treated as single-owner identities across live processes; duplicate live joins are rejected.
- Participant cleanup on process exit is best-effort via `atexit`. Hard kills can leave stale participants behind.
- `get_status` is not an atomic snapshot across both files. Counts can reflect slightly different moments.
- Input strings are trimmed before validation and storage.
- Read-oriented tools enforce a hard maximum of `100` messages per call.
- Context control is handled by cursors, summaries, and `get_handoff`. The message log is still durable on disk.
- This version does not rotate `messages.jsonl`; rotation would require changing the current ID-allocation contract.

## Project Files

- [`AGENTS.md`](./AGENTS.md)
- [`AGENTS.local.example`](./AGENTS.local.example)
- [`chatroom_mcp_server.py`](./chatroom_mcp_server.py)
- [`chatroom_monitor.py`](./chatroom_monitor.py)
- [`SPEC.md`](./SPEC.md)
- [`ROADMAP.md`](./ROADMAP.md)
- [`tests/test_chatroom_mcp_server.py`](./tests/test_chatroom_mcp_server.py)
