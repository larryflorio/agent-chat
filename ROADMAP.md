# Roadmap

## Near-Term Hardening

- Add a small maintenance path for clearing stale participant records without manual file edits.
- Add deeper crash-recovery and concurrent-join coverage beyond the current concurrency smoke test.
- Decide whether stale-presence recovery remains explicit/manual in v1 or gets a dedicated maintenance tool before v2.

## Future: True Multi-Session Identity

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

- Treat this as a v2 design task.
- Do not partially simulate process identity with more in-memory checks.
- Keep the current single-owner name model until duplicate-name or stale-session friction justifies the added complexity.
