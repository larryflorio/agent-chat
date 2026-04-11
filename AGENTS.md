# Repository Guidelines

## Project Structure & Module Organization

This repository is currently a minimal prompt-driven project. The root contains [`prompt-agent-chatroom-mcp.md`](/Users/lf/Documents/claude_projects/agent-chat/prompt-agent-chatroom-mcp.md), which defines the required behavior for a local Python MCP chatroom server.

If you implement the prompt, keep the generated runtime in the repo root as `chatroom_mcp_server.py`. Runtime state should not be committed; per the spec, use `.chatroom/` for local message and participant files and ignore that directory in Git.

## Build, Test, and Development Commands

There is no formal build system in the current workspace. Use direct Python commands:

- `python3 chatroom_mcp_server.py` runs the MCP server over stdio.
- `python3 -m py_compile chatroom_mcp_server.py` performs a quick syntax check.
- `python3 -m pytest` is the expected test entrypoint if a test suite is added later.

Keep commands repo-local and dependency-light. The prompt explicitly limits dependencies to `mcp` plus the Python standard library.

## Coding Style & Naming Conventions

Use Python with 4-space indentation and standard library types/hints. Prefer clear, small helper functions over framework-heavy abstractions. Follow the prompt’s constraints exactly:

- single-file implementation
- no external deps beyond `mcp`
- filesystem locking via `fcntl.flock`
- plain JSON/JSONL storage under `.chatroom/`

Use `snake_case` for functions and variables. Keep tool names aligned with the prompt: `join`, `leave`, `send_message`, `read_messages`, `list_participants`, `get_status`.

## Testing Guidelines

No tests are present yet. If you add them, keep them under `tests/` and name files `test_*.py`. Prioritize behavior that can regress quietly: file locking, message ID assignment, participant rejoin/leave behavior, and filtering in `read_messages`.

## Commit & Pull Request Guidelines

No Git history is available in this workspace, so no local commit convention can be inferred. Use short imperative commit subjects such as `Add locked message append logic`. PRs should include a concise summary, the prompt requirement(s) addressed, and manual verification steps such as local server startup or concurrent access checks.
