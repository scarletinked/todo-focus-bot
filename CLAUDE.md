# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the bot
python bot.py

# Run all tests
pytest tests/

# Run a single test file
pytest tests/test_helpers.py

# Run a single test class or method
pytest tests/test_commands.py::TestGoCommand
pytest tests/test_commands.py::TestGoCommand::test_go_starts_session
```

## Architecture

Everything lives in `bot.py` (single-file bot). The test suite in `tests/` mirrors its logical sections.

**Core flow:**
1. User DMs the bot `go` → `start_session()` fetches today's Todoist tasks, shuffles them, creates a `ReviewSession`, and calls `show_task()`
2. `on_message` routes each DM command to the appropriate Todoist API call, then calls `finish_action()` → `show_task()` to advance
3. `daily_nudge` (discord.ext `tasks.loop`) fires at `NUDGE_HOUR` in `TIMEZONE` and calls `start_session()` automatically

**Key abstractions:**
- `ReviewSession` — manages a list of tasks with index-based advancement and a skip-and-loop mechanism (skipped tasks accumulate in `sessions.skipped` and become the new list when the main list is exhausted)
- `sessions` dict — maps Discord user ID → active `ReviewSession`; cleared on session end or `go`
- `awaiting_repo_url` dict — tracks users mid-journal-flow waiting to provide a GitHub URL
- Recurrence modes: `@randrecur` (resets to 30–50 random days) vs `@consistrecur` (Todoist advances by fixed interval); auto-assigned by `r` if neither label present

**Async pattern:** The Todoist and GitHub APIs are synchronous; all calls are wrapped with `asyncio.to_thread()` to avoid blocking the Discord event loop.

**Journal feature:** Tasks prefixed `journal ` trigger a special flow — the bot asks for a GitHub repo URL (or reads it from the task description / `JOURNAL_GITHUB_URL` env var), then `answer <text>` appends a markdown entry to `JOURNAL_FILENAME` in that repo via the GitHub Contents API.

## Environment variables

Required: `DISCORD_TOKEN`, `DISCORD_USER_ID`, `TODOIST_API_TOKEN`
Optional: `TIMEZONE` (IANA name, default `UTC`), `NUDGE_HOUR` (0–23, default `9`), `GITHUB_TOKEN`, `JOURNAL_GITHUB_URL`, `JOURNAL_FILENAME`

## License

GPLv3
