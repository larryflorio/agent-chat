# Repository Guidelines

This tracked file is for public, repository-specific agent guidance only. Put any operator-specific or private instructions in `AGENTS.local.md`, which is gitignored.

## Project Structure & Module Organization

This repository is currently a minimal spec-driven project. The root contains [`SPEC.md`](/Users/lf/Documents/claude_projects/agent-chat/SPEC.md), which defines the required behavior for a local Python MCP chatroom server.

If you implement the spec, keep the generated runtime in the repo root as `chatroom_mcp_server.py`. Runtime state should not be committed; per the spec, use `.chatroom/` for local message, participant, cursor, and summary files and ignore that directory in Git.

## Build, Test, and Development Commands

There is no formal build system in the current workspace. Use direct Python commands:

- `python3 chatroom_mcp_server.py` runs the MCP server over stdio.
- `python3 -m py_compile chatroom_mcp_server.py` performs a quick syntax check.
- `python3 -m pytest` is the expected test entrypoint if a test suite is added later.

Keep commands repo-local and dependency-light. The spec explicitly limits dependencies to `mcp` plus the Python standard library.

## Coding Style & Naming Conventions

Use Python with 4-space indentation and standard library types/hints. Prefer clear, small helper functions over framework-heavy abstractions. Follow the spec's constraints exactly:

- single-file implementation
- no external deps beyond `mcp`
- filesystem locking via `fcntl.flock`
- plain JSON/JSONL storage under `.chatroom/`

Use `snake_case` for functions and variables. Keep tool names aligned with the spec: `join`, `leave`, `send_message`, `read_messages`, `list_participants`, `get_status`, `get_cursor`, `set_cursor`, `read_unread`, `write_summary`, `read_latest_summary`, `get_handoff`.

## Testing Guidelines

No tests are present yet. If you add them, keep them under `tests/` and name files `test_*.py`. Prioritize behavior that can regress quietly: file locking, message ID assignment, participant rejoin/leave behavior, cursor updates, summary retrieval, and filtering in `read_messages` and `read_unread`.

## Commit & Pull Request Guidelines

No strict local commit convention is required. Use short imperative commit subjects such as `Add locked message append logic`. PRs should include a concise summary, the spec requirement(s) addressed, and manual verification steps such as local server startup or concurrent access checks.
