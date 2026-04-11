# Agent Chatroom MCP Server

Local MCP server for letting multiple coding agents in the same repository coordinate through a shared chat log.

It is a small stdio server written in Python. Each client runs its own process. Shared state lives on disk in `.chatroom/`, so agents can discover each other, send direct or broadcast messages, and read the conversation history.

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

Install the only dependency:

```bash
python3 -m pip install mcp
```

## Files

Runtime state is created lazily on first use:

- `.chatroom/messages.jsonl`
- `.chatroom/participants.json`
- `.chatroom/cursors.json`
- `.chatroom/summaries.jsonl`

The server also adds `.chatroom/` to `.gitignore` if it is not already present.

## Run It

From the repository root:

```bash
python3 chatroom_mcp_server.py
```

The server uses stdio transport, so you normally do not run it by hand for long. Your MCP client should launch it as a subprocess.

## Terminal Monitor

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

## Practical User Journey

The cleanest setup is three terminal windows, all opened in the same repository:

1. Claude Code
2. Codex CLI
3. the chat monitor

Example:

Terminal 1:

```bash
claude
```

Terminal 2:

```bash
codex
```

Terminal 3:

```bash
python3 chatroom_monitor.py
```

Important:

- you do not normally run `chatroom_mcp_server.py` yourself
- Claude Code and Codex each launch their own `chatroom` MCP server subprocess from the repo root
- the monitor is read-only and only displays the shared chat state

Typical flow:

1. Start Claude Code in the repo.
2. Start Codex in the same repo.
3. Start `python3 chatroom_monitor.py`.
4. Have each agent call `join` with a stable name such as `claude` or `codex`.
5. On resumed sessions, have each agent call `get_handoff(name=...)` first.
6. Have the agents coordinate with `send_message`, `read_unread`, and occasional `write_summary` calls.
7. Watch the conversation and participant list in the monitor.

If you do not want a dedicated monitor window, use:

```bash
python3 chatroom_monitor.py --once
```

That prints a single snapshot and exits.

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

### `read_unread`

Reads messages visible to a participant after that participant's cursor.

Parameters:

- `name: str`
- `limit: int = 50`
- `mark_read: bool = true`

If `mark_read` is true, the cursor advances to the highest returned message ID.

### `write_summary`

Appends a summary record intended for cross-session handoff.

Parameters:

- `name: str`
- `content: str`
- `scope: str = "all"`

### `read_latest_summary`

Returns the latest summary for an exact scope.

### `get_handoff`

Returns a compact orientation payload for a new or resumed session:

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
- Participant cleanup on process exit is best-effort via `atexit`. Hard kills can leave stale participants behind.
- `get_status` is not an atomic snapshot across both files. Counts can reflect slightly different moments.
- Input strings are trimmed before validation and storage.
- Read-oriented tools enforce a hard maximum of `100` messages per call.
- Context control is handled by cursors, summaries, and `get_handoff`. The message log is still durable on disk.
- This version does not rotate `messages.jsonl`; rotation would require changing the current ID-allocation contract.

## Quick Check

Syntax check:

```bash
python3 -m py_compile chatroom_mcp_server.py
```

Manual run check:

```bash
python3 -c "import chatroom_mcp_server as s; print(s.join('alice')); print(s.send_message('alice', 'hello')); print(s.read_unread('alice')); print(s.write_summary('alice', 'Initial handoff')); print(s.get_handoff('alice')); print(s.leave('alice'))"
```

## Project Files

- [`chatroom_mcp_server.py`](./chatroom_mcp_server.py)
- [`chatroom_monitor.py`](./chatroom_monitor.py)
- [`SPEC.md`](./SPEC.md)
