# Roadmap

## Topic-Centric V2

This is the current long-term direction for the chatroom:

- move runtime state to `.chatroom_v2/`
- make topics explicit and caller-selected
- scope messages, cursors, summaries, and handoffs by topic
- keep participant presence name-owned for now
- provide a read-only human viewer/export surface that is topic-aware

What this fixes:

- mixed-topic history in the resume path
- room-wide unread state that leaks between workstreams
- the need for humans to inspect raw JSONL state files to understand what is happening

What this does not fix:

- stale participant cleanup after crashes
- true multi-session identity
- session-scoped leave semantics
- a dedicated human write/posting surface

## Still Open

### Near-Term Hardening

- Add a small maintenance path for clearing stale participant records without manual file edits.
- Add deeper crash-recovery and concurrent-join coverage beyond the current concurrency smoke test.
- Decide whether stale-presence recovery remains explicit/manual or gets a dedicated maintenance tool.

### Future: True Multi-Session Identity

Current state:

- Participant presence is keyed primarily by participant name.
- Rejoining the same name is allowed only from the same process.
- Crashed processes can leave stale participant records that block name reuse.

Target state:

- Each live server process owns a durable `session_id` distinct from the display `name`.
- Presence is tracked per session rather than by name alone.
- `leave` removes only the calling session's presence.
- Multiple live sessions may share the same display name if that becomes desirable.
- Participant views can aggregate multiple sessions under one display name.

Likely design changes:

- Change `participants.json` from a simple `name -> record` map to a session-aware structure.
- Generate a `session_id` during `join` and persist it for that process lifetime.
- Make cleanup and leave semantics session-scoped.
- Decide whether stale-session cleanup is explicit, heuristic, or heartbeat-based.
- Decide whether direct messages continue to target display names or may optionally target sessions.

Why this is not a small patch:

- It changes the persistence contract.
- It changes tool semantics, especially `join`, `leave`, and `list_participants`.
- It requires a compatibility story for existing repos and existing `.chatroom/participants.json` state.

Recommendation:

- Treat this as a later design task.
- Keep the current single-owner name model until duplicate-name or stale-session friction justifies the added complexity.

### Future: Human Interaction Surface

Current state:

- Humans can inspect chats through the read-only terminal viewer and JSON export path.
- Humans can also use navigation conveniences like `--unread-only` and `--latest-topic` to reach the relevant topic faster.
- Humans do not have a first-class write or topic-management surface outside MCP tool callers.

Target state:

- Humans can post messages, open topics, and close topics through a dedicated user-facing interface if and when that is intentionally designed.
- The human surface remains local-first and consistent with the MCP persistence contract.
- Human writes follow the same topic and visibility semantics as agent writes.

Likely design changes:

- Decide whether the write surface is terminal-first, web-based, or both.
- Add validation and guardrails for human-authored participant names and topic actions.
- Define whether humans authenticate as named participants, ephemeral sessions, or a distinct actor class.
- Ensure any user-facing write path preserves locking, append-only log semantics, and topic-scoped cursors/summaries.

Recommendation:

- Treat this as a later design task after session identity and stale-participant maintenance are clearer.
- Keep the current read-only viewer/export surface as the supported human path for now.
