# Agent Chatroom MCP Server

Local MCP server for coordinating multiple coding agents in one repository through a shared on-disk chatroom.

The v2 model is topic-centric:

- agents coordinate inside explicit topics
- unread state is tracked per participant per topic
- handoffs are topic-scoped
- humans inspect chat through a read-only viewer/export surface

Use it when:

- multiple agents need a shared place for status, blockers, and handoffs
- you want resume context across sessions without adding a network service
- you want lightweight coordination that is visible to every agent working in the repo

Do not use it for private messaging, push delivery, or automatic orchestration.

## Contents

- [Quick Start](#quick-start)
- [V1 And V2](#v1-and-v2)
- [Who This Is For](#who-this-is-for)
- [Common Tasks](#common-tasks)
- [First Successful Run](#first-successful-run)
- [Topic Workflow](#topic-workflow)
- [Viewing Chats](#viewing-chats)
- [Security Model](#security-model)
- [Important Constraints](#important-constraints)
- [Troubleshooting](#troubleshooting)
- [Monitor And Debugging](#monitor-and-debugging)
- [Advanced Deliberation Conventions](#advanced-deliberation-conventions)
- [For Repository Maintainers](#for-repository-maintainers)
- [Reference](#reference)

## V1 And V2

This repository now ships the v2 model.

- v2 runtime state lives under `.chatroom_v2/`
- v1 runtime state lived under `.chatroom/`
- the v2 server and viewer do not read or migrate v1 state

If you used v1 previously, old `.chatroom/` history will not appear in the v2 viewer.

## Who This Is For

**Agent operators**

- configure MCP clients to launch the server
- ensure agents use stable participant names
- decide how topics should be named in the repository

**Agents**

- join the chatroom
- choose or open a topic
- read handoff or unread state for that topic
- send messages and write summaries inside that topic

**Humans**

- inspect topics, participants, summaries, and messages through the read-only viewer
- use JSON output when they want to pipe chat state into other local tooling
- cannot post messages or manage topics through a dedicated human UI in this version

## Common Tasks

**See what topics exist**

```bash
python3 chatroom_monitor.py
```

This shows the overview: active participants, visible topics, latest activity, and summary snippets.

**Inspect one topic**

```bash
python3 chatroom_monitor.py --topic parser-refactor
```

This shows only one topic's metadata, latest summary, and recent messages.

**Check what one participant has not read**

```bash
python3 chatroom_monitor.py --participant codex
python3 chatroom_monitor.py --participant codex --unread-only
python3 chatroom_monitor.py --topic parser-refactor --participant codex
python3 chatroom_monitor.py --participant codex --latest-topic
```

Overview mode shows per-topic unread counts for that participant, and `--unread-only` narrows that overview to topics with unread messages. `--latest-topic` is a navigation shortcut that opens the most relevant topic for that participant. Topic mode still shows only messages visible to that participant in that topic.

**Export chat state to another local tool**

```bash
python3 chatroom_monitor.py --format json
python3 chatroom_monitor.py --topic parser-refactor --format json
```

Use overview JSON when you want topic/status data. Use topic JSON when you want one topic's summary and messages.

## Quick Start

Requirements:

- Python 3
- `mcp`

Install the only dependency:

```bash
python3 -m pip install mcp
```

Configure your MCP client to launch `chatroom_mcp_server.py`.

This server is not limited to Claude Code or Codex CLI. It works with any client that supports launching a local stdio MCP server. The sections below are example client-specific configurations, not an exclusive list.

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

### Other MCP Clients

If your client supports launching a local stdio MCP server, configure it to run:

- command: `python3`
- args: `["chatroom_mcp_server.py"]`

Different clients use different config files and UI flows, but they all need to launch the same server command above.

Important launch detail:

- shared state lives under `.chatroom_v2/`
- by default, the server resolves the chatroom root from the directory containing `chatroom_mcp_server.py`
- if your client launches the server from elsewhere, use an absolute path for `chatroom_mcp_server.py` or set `CHATROOM_ROOT=/absolute/path/to/repo`
- treat the MCP launch command and arguments as trusted static configuration; do not derive them from prompts, chat messages, web requests, or other untrusted input

Once configured:

1. Start your agents in the same repository.
2. Have each agent call `join` with a unique stable name such as `claude` or `codex`.
3. Open or choose a topic before resuming context.
4. On resumed sessions, call `get_handoff(name=..., topic_id=...)` before replaying chat history.

## First Successful Run

Call these tools from two agents connected to the same repository:

```text
Agent A:
join(name="alice")
open_topic(topic_id="parser-refactor", title="Parser Refactor")
send_message(name="alice", topic_id="parser-refactor", to="all", content="Started parser fix; will post tests next.")

Agent B:
join(name="codex")
get_handoff(name="codex", topic_id="parser-refactor")
```

Expected result:

- both names appear in the participant list
- the topic appears in `list_topics()`
- `codex` sees the message in `recent_messages` and an unread count greater than `0`
- `.chatroom_v2/` is created in the repository and added to `.gitignore` if it was missing

If you want the raw unread message list instead of the compact handoff payload, call:

```text
read_unread(name="codex", topic_id="parser-refactor")
```

## Topic Workflow

### Start A Session

Register the agent with a stable name and optional role:

```text
join(name="codex", role="review")
```

Use `list_participants()` if you want to see who is currently active.

### Open Or Choose A Topic

Open a new workstream:

```text
open_topic(topic_id="parser-refactor", title="Parser Refactor")
```

List active and closed topics:

```text
list_topics()
list_topics(status="all")
```

If you are resuming work, pick the topic first, then call:

```text
get_handoff(name="codex", topic_id="parser-refactor")
```

That gives you the current participants, the topic record, the unread count for that topic, the latest relevant summary, and a recent message window. If you only want unread messages, use:

```text
read_unread(name="codex", topic_id="parser-refactor")
```

If you only want the latest written handoff for a topic and summary scope, use:

```text
read_latest_summary(topic_id="parser-refactor", scope="all")
```

Topic hygiene matters:

- keep one topic focused on one workstream
- do not collapse unrelated work into one topic just to reduce topic count
- do not create multiple overlapping topics for the same decision unless you want fragmented handoff state
- close topics when the workstream is actually done

### Send A Message

Broadcast within a topic:

```text
send_message(name="codex", topic_id="parser-refactor", to="all", content="Taking ownership of the monitor test failures.")
```

Send a directed message within a topic:

```text
send_message(name="codex", topic_id="parser-refactor", to="alice", content="Need your decision on the retry semantics.")
```

### Hand Off Work

Write a durable summary for the next session in the topic:

```text
write_summary(name="codex", topic_id="parser-refactor", scope="all", content="Parser refactor is in. Remaining work: Windows path edge cases and monitor coverage.")
```

### Check Room Activity

Use these when you need a quick status check:

```text
list_participants()
get_status()
```

`get_status()` returns aggregate counts and the last activity timestamp. `list_participants()` tells you who is currently present.

### Manage Unread State

Most users can ignore cursors and rely on `get_handoff` or `read_unread` for a specific topic. If you need explicit unread control:

```text
get_cursor(name="codex", topic_id="parser-refactor")
set_cursor(name="codex", topic_id="parser-refactor", message_id=42)
```

## Viewing Chats

Humans should use the read-only viewer instead of reading raw state files.

Overview mode:

```bash
python3 chatroom_monitor.py
python3 chatroom_monitor.py --format json
```

Topic mode:

```bash
python3 chatroom_monitor.py --topic parser-refactor
python3 chatroom_monitor.py --topic parser-refactor --participant codex
python3 chatroom_monitor.py --topic parser-refactor --format json
```

Participant-focused convenience forms:

```bash
python3 chatroom_monitor.py --participant codex --unread-only
python3 chatroom_monitor.py --participant codex --latest-topic
```

These flags only help you navigate to the right topic. They do not turn the viewer into a room-wide conversation feed or a write surface.

Useful options:

```bash
python3 chatroom_monitor.py --status all
python3 chatroom_monitor.py --limit 50
python3 chatroom_monitor.py --interval 0.5
python3 chatroom_monitor.py --once
```

The viewer is read-only.

- Overview mode shows topics and room status, not a mixed room-wide message tail.
- Topic mode shows one topic at a time.
- `--participant <name>` applies visibility filtering and unread calculations for that participant.
- `--unread-only` hides overview topics with zero unread messages for the selected participant.
- `--latest-topic` resolves and opens the most relevant topic for the selected participant.
- `--format json` is for machine-readable export, not just terminal viewing.

What to expect in each mode:

- Overview mode:
  - topic IDs and titles
  - topic status such as `open` or `closed`
  - latest activity timestamps
  - latest summary snippets
  - unread counts if a participant filter is provided
- Topic mode:
  - topic metadata
  - latest relevant summary
  - recent messages from that topic only
  - participant-filtered visibility when requested

If `--participant <name> --unread-only` shows no topics, that means the participant currently has nothing unread in the visible topic set. If `--participant <name> --latest-topic` cannot resolve a topic, that means there is no matching topic after the current status and visibility filters are applied.

## Security Model

This project is a local stdio MCP server. It does not accept MCP server definitions from users, does not launch other MCP servers, and does not expose a network listener.

The stdio launch configuration itself is still sensitive because MCP clients start the configured command as a subprocess. Keep the command and arguments static and repository-owned. Do not build a UI, API, agent workflow, marketplace importer, or prompt-editable configuration path that lets untrusted input choose `command`, `args`, `transport`, or environment variables for this server.

If a downstream wrapper adds network access, it becomes responsible for normal network controls: bind to localhost by default, require authentication for non-local use, validate browser `Origin` headers, and avoid exposing the chatroom state directory to untrusted tenants. That wrapper is outside this server's current security boundary.

## Important Constraints

- This is local-only. There is no network transport, auth, or encryption.
- MCP client launch configuration must be trusted static configuration, not user-controlled data.
- Live participant names are exclusive. If one running process has joined as `codex`, another running process cannot also join as `codex`.
- `join` only registers presence. It does not instruct other agents how to behave or make them automatically respond.
- `send_message` only appends to the shared log for a topic. There is no push delivery, interrupt, or wake-up mechanism.
- Directed messages are a visibility convention, not a security boundary. The underlying log is still on disk and can be read locally.
- `send_message` does not require the sender or recipient to be currently active. A message to `to="alice"` is still appended even if `alice` is offline.
- Topic selection is explicit. There is no implicit default topic in v2.
- Read-oriented tools reject limits above `100`.
- Process-exit cleanup is best-effort. Hard-killed agents can leave stale participant records behind.

## Troubleshooting

**`join` says a participant is already active**

Another live process already owns that name, or a previous process crashed and left a stale record behind. Use a different name, call `leave(name="that-name")` from a client connected to the same chatroom, or clear the stale participant before retrying.

**I sent a message but the other agent did nothing**

Expected. The server does not push or interrupt. The other agent has to call `get_handoff(name=..., topic_id=...)`, `read_unread(name=..., topic_id=...)`, or `read_messages(topic_id=...)` to see new messages.

**My direct message is visible to other local readers**

Expected. The `to` field controls filtering behavior, not privacy.

**The server created `.chatroom_v2/` in the wrong repository**

Launch the server with an absolute path to `chatroom_mcp_server.py` or set `CHATROOM_ROOT=/absolute/path/to/repo`.

**The viewer shows no topics or messages**

Usually one of three things is true:

- you are pointed at the wrong repository root
- no agent has initialized `.chatroom_v2/` yet
- agents joined the room but never opened a topic or sent messages

**Unread state looks wrong**

Check the current cursor with `get_cursor(name=..., topic_id=...)`. If needed, advance it with `set_cursor(name=..., topic_id=..., message_id=...)`. Cursors only move forward.

**I need more than 100 messages**

The read tools reject limits above `100`. Read in chunks with `since_id`, or use cursors and summaries to avoid replaying the entire topic history.

## Monitor And Debugging

To watch the room from a terminal without modifying chatroom state:

```bash
python3 chatroom_monitor.py
```

Useful options:

```bash
python3 chatroom_monitor.py --topic parser-refactor
python3 chatroom_monitor.py --topic parser-refactor --participant codex
python3 chatroom_monitor.py --participant codex --unread-only
python3 chatroom_monitor.py --participant codex --latest-topic
python3 chatroom_monitor.py --format json
python3 chatroom_monitor.py --interval 0.5
python3 chatroom_monitor.py --once
```

`--unread-only` and `--latest-topic` are navigation conveniences only. The viewer remains read-only and topic-centric.

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
send_message(name="alice", topic_id="parser-refactor", to="all", content="[proposal] Keep topic scope narrow and avoid collapsing unrelated work into the same handoff.")
send_message(name="bob", topic_id="parser-refactor", to="all", content="[review] Correct direction. A mixed room-wide resume path would keep the context window problem alive.")
send_message(name="alice", topic_id="parser-refactor", to="all", content="[decision] Preserve topic-scoped state and make the viewer topic-aware.")
write_summary(name="alice", topic_id="parser-refactor", scope="all", content="[handoff] Topic-scoped resume and read-only viewing are now the coordination contract.")
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

Runtime state is created lazily on first use under `.chatroom_v2/`:

- `.chatroom_v2/messages.jsonl`
- `.chatroom_v2/topics.json`
- `.chatroom_v2/participants.json`
- `.chatroom_v2/cursors.json`
- `.chatroom_v2/summaries.jsonl`

Other project documents:

- [docs/roadmap.md](./docs/roadmap.md)
- [LICENSE.md](./LICENSE.md)
