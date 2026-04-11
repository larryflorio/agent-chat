# Agent Chatroom MCP Server

Local MCP server for letting multiple coding agents in the same repository coordinate through a shared chat log.

It is a small stdio server written in Python. Each client runs its own process. Shared state lives on disk in `.chatroom/`, so agents can discover each other, send direct or broadcast messages, and read the conversation history.

## What It Does

- registers active participants
- sends broadcast messages to `all`
- sends direct messages to a named participant
- reads messages after a given message ID
- lists active participants
- reports basic chatroom status

This is local-only. No network transport, auth, or encryption.

## Requirements

- Python 3
- `mcp` Python package

Install the only dependency:

```bash
python3 -m pip install mcp
```

## Files

Runtime state is created lazily on first use:

- `.chatroom/messages.jsonl`
- `.chatroom/participants.json`

The server also adds `.chatroom/` to `.gitignore` if it is not already present.

## Run It

From the repository root:

```bash
python3 chatroom_mcp_server.py
```

The server uses stdio transport, so you normally do not run it by hand for long. Your MCP client should launch it as a subprocess.

## Configure Claude Code

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

## Configure Codex CLI

Add this to `.codex/config.toml`:

```toml
[mcp_servers.chatroom]
command = "python3"
args = ["chatroom_mcp_server.py"]
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

## Typical Agent Flow

1. Agent starts and calls `join`.
2. Agent calls `read_messages` with its last seen message ID.
3. Agent sends status updates with `send_message`.
4. Agent polls `read_messages` as needed.
5. Agent calls `leave` when done.

## Operational Notes

- Message IDs are assigned under an exclusive file lock, so concurrent writers still get unique sequential IDs.
- Participant cleanup on process exit is best-effort via `atexit`. Hard kills can leave stale participants behind.
- `get_status` is not an atomic snapshot across both files. Counts can reflect slightly different moments.
- Input strings are trimmed before validation and storage.

## Quick Check

Syntax check:

```bash
python3 -m py_compile chatroom_mcp_server.py
```

Manual run check:

```bash
python3 -c "import chatroom_mcp_server as s; print(s.join('alice')); print(s.send_message('alice', 'hello')); print(s.read_messages(participant='alice')); print(s.leave('alice'))"
```

## Project Files

- [`chatroom_mcp_server.py`](./chatroom_mcp_server.py)
- [`prompt-agent-chatroom-mcp.md`](./prompt-agent-chatroom-mcp.md)
