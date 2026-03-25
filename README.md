# todo-focus-bot

A self-hosted Discord bot that helps you review your Todoist tasks due today, one at a time, via DM.

DM the bot `go` and it walks you through each task. For each one you can mark it done, bump it to a future date, make it recurring, or skip it. Skipped tasks loop back at the end. A daily nudge sends you the list automatically at a configured time each morning.

## Setup

### 1. Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** and give it a name
3. Go to the **Bot** tab and click **Add Bot**
4. Under **Privileged Gateway Intents**, enable **Message Content Intent**
5. Copy the bot token

### 2. Invite the Bot to a Server

1. Go to **OAuth2 > URL Generator**
2. Under *Scopes*, select `bot`
3. Under *Bot Permissions*, select `Send Messages` and `Read Message History`
4. Copy the generated URL and open it in your browser to add the bot to a server

> The bot only interacts via DM, but it must share at least one server with you to be reachable.

### 3. Get Your Todoist API Token

1. Go to [Todoist Settings > Integrations > Developer](https://todoist.com/app/settings/integrations/developer)
2. Copy your API token

### 4. Get Your Discord User ID

1. In Discord, go to **Settings > Advanced** and enable **Developer Mode**
2. Right-click your own username anywhere in Discord and select **Copy User ID**

### 5. Configure Environment

```
cp .env.example .env
```

Edit `.env` and fill in the required values:

```
DISCORD_TOKEN=your_discord_bot_token
DISCORD_USER_ID=your_discord_user_id
TODOIST_API_TOKEN=your_todoist_api_token
```

By default the daily nudge fires at 9:00 AM UTC. Set `TIMEZONE` and `NUDGE_HOUR` to match your location:

```
TIMEZONE=America/New_York
NUDGE_HOUR=8
```

`TIMEZONE` accepts any [IANA timezone name](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones).

### 6. Install and Run

```
pip install -r requirements.txt
python bot.py
```

You should see `Bot ready` in the console.

## Commands

DM the bot `go` to start reviewing your tasks due today.

### Non-recurring tasks

| Command | Action |
|---------|--------|
| `d` | Mark as done |
| `t` | Move to tomorrow |
| `<N>` | Move *N* days out (e.g. `14`) |
| `b` | Bump to a random date 5–14 days out |
| `bb` | Big bump — 15–30 days out |
| `n` | Skip, come back later |
| `r` | Make recurring (random 30–50 days, tagged `@randrecur`) |
| `r <N>` | Make recurring every *N* days (tagged `@consistrecur`) |
| `h` | Show help |

### Recurring tasks

| Command | Action |
|---------|--------|
| `t` | Move to tomorrow |
| `<N>` | Move *N* days out |
| `n` | Skip, come back later |
| `r` | Resolve: marks done if `@consistrecur`; resets interval if `@randrecur` |
| `rr` | Tag as random recurrence (`@randrecur`) |
| `cr` | Tag as consistent recurrence (`@consistrecur`) |
| `del` | Delete the task permanently |
| `h` | Show help |

### Other

- Send `go` at any time to re-fetch today's tasks and start a fresh session.
- Send `add <task name>` to create a task due today and immediately start a session.
- Skipped tasks loop back after you've gone through the full list.

## Recurrence modes

The bot uses two Todoist labels to track how recurring tasks should be handled:

- **`@randrecur`** — each time you resolve the task, its next due date resets to a random 30–50 days out. Good for infrequent tasks where exact timing doesn't matter.
- **`@consistrecur`** — each time you resolve the task, Todoist advances it by its fixed interval. Good for habits and regular cadences.

If a task has no label, `r` auto-assigns one based on interval: ≤7 days → `@consistrecur`, otherwise → `@randrecur`.

## Journal tasks (optional)

If a Todoist task's name starts with `journal `, the bot will prompt you to respond and append your answer to a markdown file in a GitHub repository — useful for a notes vault such as [Obsidian](https://obsidian.md).

**Setup:**

1. Create a GitHub Personal Access Token with `repo` scope and add it to `.env`:
   ```
   GITHUB_TOKEN=your_github_pat
   ```
2. Either set a default repo URL:
   ```
   JOURNAL_GITHUB_URL=https://github.com/you/your-repo
   ```
   Or add a `repo: https://github.com/you/your-repo` line to the task's description in Todoist.

**Usage:**

Name a Todoist task `journal What am I grateful for today?` (due today). When the bot reaches it, reply with `answer <your response>`. The bot appends an entry under today's date heading in the configured file and marks the task done.

The journal file path within the repo defaults to `Daily Journal.md`. Override with:
```
JOURNAL_FILENAME=Notes/Journal.md
```

## Running tests

```
pytest tests/
```
