# Downstream Setup

Use this note if you are adding the chatroom MCP server to another repository and want the agents in that repository to use it consistently.

## What To Add To The Consuming Repository

After adding the chatroom server to the repository, do two things:

1. Configure the MCP client to launch `chatroom_mcp_server.py`.
2. Add a short chatroom workflow section to that repository's agent instructions.

The exact configuration syntax is client-specific, but any client that supports local stdio MCP servers can launch this server.

The consuming repository's own instruction files control agent behavior. Agents there will not automatically inherit this repository's `AGENTS.md`.

## Suggested `AGENTS.md` Snippet

```md
## Chatroom Coordination

When using the `chatroom` MCP server for multi-agent work:

- Call `join(name=...)` when starting work.
- On resumed work, call `get_handoff(name=...)`.
- Prefer `read_unread(name=...)` or the latest summary over replaying the full log.
- Send coordination updates with `send_message(...)`.
- Write a handoff with `write_summary(...)` before handing work across sessions.
- Call `leave(name=...)` when done.
- Instruct every participating agent to check the chatroom and act on relevant messages; joining alone does not create an automatic relay or response loop.

Use the chatroom for ownership, status, blockers, and handoffs. Keep messages compact.

For changes affecting persistence, locking, tool semantics, or cross-process behavior:

- use `[proposal]` for the initial direction
- use `[review]` for critique focused on correctness, risk, and tests
- use `[decision]` when a direction is chosen
- use `[handoff]` in `write_summary` only for the final synthesized state

Prefer at least one substantive review before a decision on non-trivial changes.
```

## Suggested `CLAUDE.md` Snippet

```md
## Chatroom Coordination

When the `chatroom` MCP server is available:

- Join the chatroom at the start of work with `join`.
- Use `get_handoff` and `read_unread` to resume context efficiently.
- Send concise progress or blocker updates with `send_message`.
- Write `write_summary` before handoff or session end when continuity matters.
- Leave the chatroom with `leave` when work is complete.
- Do not assume another agent will see a message unless that agent is also instructed to read from the chatroom.
```

## Source Of Truth

Exact tool semantics live in [spec.md](./spec.md). Keep downstream instructions short and behavioral. Use the consuming repository's own instruction files to say when and why agents should call the tools.
