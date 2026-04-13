# Agent Chatroom MCP Server

Local MCP server for coordinating multiple coding agents in one repository through a shared on-disk chatroom.

Use it when:

- multiple agents need a shared place for status, blockers, and handoffs
- you want resume context across sessions without adding a network service
- you want lightweight coordination that is visible to every agent working in the repo

Do not use it for private messaging, push delivery, or automatic orchestration.

## Contents

- [Quick Start](#quick-start)
- [First Successful Run](#first-successful-run)
- [Common Workflows](#common-workflows)
- [Important Constraints](#important-constraints)
- [Troubleshooting](#troubleshooting)
- [Monitor And Debugging](#monitor-and-debugging)
- [Advanced Deliberation Conventions](#advanced-deliberation-conventions)
- [For Repository Maintainers](#for-repository-maintainers)
- [Reference](#reference)

## Quick Start

Requirements:

- Python 3
- `mcp`

Install the only dependency:

```bash
python3 -m pip install mcp
```

Configure your MCP client to launch `chatroom_mcp_server.py`.

### Claude Code

Create a `.mcp.json` file in the project root:

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

### Codex CLI

Add this to `.codex/config.toml`:

```toml
[mcp_servers.chatroom]
command = "python3"
args = ["chatroom_mcp_server.py"]
```

Important launch detail:

- shared state lives under `.chatroom/`
- by default, the server resolves the chatroom root from the directory containing `chatroom_mcp_server.py`
- if your client launches the server from elsewhere, use an absolute path for `chatroom_mcp_server.py` or set `CHATROOM_ROOT=/absolute/path/to/repo`

Once configured:

1. Start your agents in the same repository.
2. Have each agent call `join` with a unique stable name such as `claude` or `codex`.
3. On resumed sessions, call `get_handoff(name=...)` before replaying chat history.

## First Successful Run

Call these tools from two agents connected to the same repository:

```text
Agent A:
join(name="alice")

Agent B:
join(name="codex")

Agent A:
send_message(name="alice", to="codex", content="Started parser fix; will post tests next.")

Agent B:
get_handoff(name="codex")
```

Expected result:

- both names appear in the participant list
- `codex` sees the message in `recent_messages` and an unread count greater than `0`
- `.chatroom/` is created in the repository and added to `.gitignore` if it was missing

If you want the raw unread message list instead of the compact handoff payload, call:

```text
read_unread(name="codex")
```

## Common Workflows

### Start A Session

Register the agent with a stable name and optional role:

```text
join(name="codex", role="review")
```

Use `list_participants()` if you want to see who is currently active.

### Resume Work

Use `get_handoff` first when returning to a task:

```text
get_handoff(name="codex")
```

That gives you the current participants, unread count, latest relevant summary, and a recent message window. If you only want unread messages, use:

```text
read_unread(name="codex")
```

If you only want the latest written handoff for a scope, use:

```text
read_latest_summary(scope="all")
```

### Send A Message

Broadcast to everyone:

```text
send_message(name="codex", to="all", content="Taking ownership of the monitor test failures.")
```

Send a directed message:

```text
send_message(name="codex", to="alice", content="Need your decision on the retry semantics.")
```

### Hand Off Work

Write a durable summary for the next session:

```text
write_summary(name="codex", scope="all", content="Parser refactor is in. Remaining work: Windows path edge cases and monitor coverage.")
```

### Check Room Activity

Use these when you need a quick status check:

```text
list_participants()
get_status()
```

`get_status()` returns aggregate counts and the last activity timestamp. `list_participants()` tells you who is currently present.

### Manage Unread State

Most users can ignore cursors and rely on `get_handoff` or `read_unread`. If you need explicit unread control:

```text
get_cursor(name="codex")
set_cursor(name="codex", message_id=42)
```

## Important Constraints

- This is local-only. There is no network transport, auth, or encryption.
- Live participant names are exclusive. If one running process has joined as `codex`, another running process cannot also join as `codex`.
- `join` only registers presence. It does not instruct other agents how to behave or make them automatically respond.
- `send_message` only appends to the shared log. There is no push delivery, interrupt, or wake-up mechanism.
- Directed messages are a visibility convention, not a security boundary. The underlying log is still on disk and can be read locally.
- `send_message` does not require the sender or recipient to be currently active. A message to `to="alice"` is still appended even if `alice` is offline.
- Read-oriented tools reject limits above `100`.
- Process-exit cleanup is best-effort. Hard-killed agents can leave stale participant records behind.

## Troubleshooting

**`join` says a participant is already active**

Another live process already owns that name, or a previous process crashed and left a stale record behind. Use a different name, call `leave(name="that-name")` from a client connected to the same chatroom, or clear the stale participant before retrying.

**I sent a message but the other agent did nothing**

Expected. The server does not push or interrupt. The other agent has to call `get_handoff`, `read_unread`, or `read_messages` to see new messages.

**My direct message is visible to other local readers**

Expected. The `to` field controls filtering behavior, not privacy.

**The server created `.chatroom/` in the wrong repository**

Launch the server with an absolute path to `chatroom_mcp_server.py` or set `CHATROOM_ROOT=/absolute/path/to/repo`.

**Unread state looks wrong**

Check the current cursor with `get_cursor(name=...)`. If needed, advance it with `set_cursor(name=..., message_id=...)`. Cursors only move forward.

**I need more than 100 messages**

The read tools reject limits above `100`. Read in chunks with `since_id`, or use cursors and summaries to avoid replaying the entire log.

## Monitor And Debugging

To watch the room from a terminal without modifying chatroom state:

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

For direct server debugging from the repository root:

```bash
python3 chatroom_mcp_server.py
```

The server uses stdio transport, so in normal use your MCP client launches it as a subprocess.

## Advanced Deliberation Conventions

For non-trivial design or implementation work, use the chatroom as a staged discussion log rather than a flat stream of status updates.

Suggested prefixes:

- `[proposal]` initial plan, diagnosis, or patch direction
- `[review]` critique of a proposal
- `[decision]` chosen direction
- `[blocker]` unresolved issue preventing progress
- `[handoff]` final cross-session summary

Recommended flow:

1. Post one `[proposal]`.
2. Collect one or more `[review]` messages.
3. Post one `[decision]`.
4. If the work spans sessions, write one `[handoff]` summary with `write_summary`.

Example:

```text
send_message(name="alice", to="all", content="[proposal] Keep v1 participant identity name-based. Add documentation and tests for stale participant recovery instead of changing persistence semantics.")
send_message(name="bob", to="all", content="[review] Correct direction. Adding heuristic stale-session detection now would change failure semantics and complicate cross-process coordination.")
send_message(name="alice", to="all", content="[decision] Preserve current v1 semantics. Document manual stale-participant cleanup and add coverage for rejoin and leave behavior.")
write_summary(name="alice", scope="all", content="[handoff] Decided not to introduce session ids or heartbeat recovery in v1. Current model remains name-owned, process-local, and explicitly cleaned up.")
```

Use the tools at different levels of fidelity:

- `send_message` for discussion, proposals, critique, and blockers
- `write_summary` for final synthesis and cross-session handoff
- `get_handoff` for compact resume context

## For Repository Maintainers

If you install this MCP server into another repository, the agents in that repository will follow that repository's own instruction files, not this repository's `AGENTS.md`.

Maintainer-specific setup guidance and reusable instruction snippets live in [docs/downstream-setup.md](./docs/downstream-setup.md).

This repository also includes:

- shared public agent guidance in [AGENTS.md](./AGENTS.md)
- an ignored template for private local instructions in [AGENTS.local.example](./AGENTS.local.example)

## Reference

Authoritative tool semantics live in [docs/spec.md](./docs/spec.md).

Runtime state is created lazily on first use under `.chatroom/`:

- `.chatroom/messages.jsonl`
- `.chatroom/participants.json`
- `.chatroom/cursors.json`
- `.chatroom/summaries.jsonl`

Other project documents:

- [docs/roadmap.md](./docs/roadmap.md)
- [LICENSE.md](./LICENSE.md)
