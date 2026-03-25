import base64
import discord
from discord.ext import tasks
import os
import random
import re
import asyncio
import requests
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from todoist_api_python.api import TodoistAPI

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TODOIST_API_TOKEN = os.getenv("TODOIST_API_TOKEN")
DISCORD_USER_ID = int(os.getenv("DISCORD_USER_ID"))
JOURNAL_FILENAME = os.getenv("JOURNAL_FILENAME", "Daily Journal.md")
TIMEZONE = os.getenv("TIMEZONE", "UTC")
NUDGE_HOUR = int(os.getenv("NUDGE_HOUR", "9"))

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
todoist = TodoistAPI(TODOIST_API_TOKEN)

sessions = {}
# Journal flow: when a journal task has no repo URL, we wait for URL or skip
awaiting_repo_url = {}


class ReviewSession:
    """Tracks state for a single task-review session."""

    def __init__(self, tasks):
        self.tasks = list(tasks)
        self.index = 0
        self.skipped = []
        self.looped = False

    @property
    def current(self):
        if 0 <= self.index < len(self.tasks):
            return self.tasks[self.index]
        return None

    @property
    def remaining(self):
        return max(0, len(self.tasks) - self.index)

    def skip(self):
        """Skip the current task (can revisit later) and advance."""
        if self.current:
            self.skipped.append(self.current)
        return self._advance()

    def advance(self):
        """Advance past a handled task."""
        return self._advance()

    def _advance(self):
        self.index += 1
        if self.index >= len(self.tasks):
            if self.skipped:
                self.tasks = self.skipped
                self.skipped = []
                self.index = 0
                self.looped = True
                return True
            return False
        return True


LABEL_RAND = "randrecur"
LABEL_CONSIST = "consistrecur"


# -- Helpers -------------------------------------------------------------------

def is_recurring(task):
    return task.due is not None and task.due.is_recurring


def get_recur_mode(task):
    """Determine the recurrence mode from labels.

    Returns 'rand', 'consist', or None if neither label is present.
    """
    labels = task.labels or []
    if LABEL_RAND in labels:
        return "rand"
    if LABEL_CONSIST in labels:
        return "consist"
    return None


def get_recurrence_days(task):
    """Extract the recurrence interval in days from a task's due string.

    Returns None if the interval can't be determined.
    """
    if not task.due or not task.due.string:
        return None

    s = task.due.string.lower()

    if re.search(r"every!?\s+other\s+day", s):
        return 2
    if re.search(r"every!?\s+day\b", s):
        return 1

    m = re.search(r"every!?\s+(\d+)\s+days?", s)
    if m:
        return int(m.group(1))

    if re.search(r"every!?\s+other\s+week", s):
        return 14
    if re.search(r"every!?\s+week\b", s):
        return 7

    m = re.search(r"every!?\s+(\d+)\s+weeks?", s)
    if m:
        return int(m.group(1)) * 7

    if re.search(r"every!?\s+other\s+month", s):
        return 60
    if re.search(r"every!?\s+month\b", s):
        return 30

    m = re.search(r"every!?\s+(\d+)\s+months?", s)
    if m:
        return int(m.group(1)) * 30

    days_of_week = (
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
        r"|mon|tue|wed|thu|fri|sat|sun"
    )
    if re.search(rf"every!?\s+({days_of_week})", s):
        return 7

    return None


# -- Journal helpers -----------------------------------------------------------

JOURNAL_PREFIX = "journal "

def is_journal_task(task):
    return task.content.strip().lower().startswith(JOURNAL_PREFIX)


def get_journal_prompt(task):
    return task.content.strip()[len(JOURNAL_PREFIX):].strip()


def get_journal_repo_url(task):
    """Parse repo URL from task description (repo: https://... or plain URL), or env fallback."""
    desc = (task.description or "").strip()
    if desc:
        m = re.search(r"repo:\s*(https://github\.com/[^\s]+)", desc, re.IGNORECASE)
        if m:
            return m.group(1).rstrip("/")
        m = re.search(r"https://github\.com/[^\s/]+/[^\s/]+", desc)
        if m:
            return m.group(0).rstrip("/")
    return os.getenv("JOURNAL_GITHUB_URL") or None


def parse_github_repo_url(url):
    """Parse https://github.com/owner/repo into (owner, repo)."""
    m = re.match(r"https?://github\.com/([^/]+)/([^/\s]+)", url.strip(), re.IGNORECASE)
    if m:
        return m.group(1), m.group(2)
    return None


def format_task(task, session):
    recurring = is_recurring(task)
    tag = ""
    if recurring:
        interval = get_recurrence_days(task)
        if interval is not None:
            tag = f" (every {interval}d)"
        else:
            tag = f" (recurring: {task.due.string})"

    parts = [f"**{task.content}**{tag}"]

    if task.description:
        parts.append(f"> {task.description}")

    status = f"[{session.remaining} remaining"
    if session.skipped:
        status += f", {len(session.skipped)} skipped"
    status += "]"
    parts.append(status)

    journal_suffix = f" | `answer` <text> to add to {JOURNAL_FILENAME}" if is_journal_task(task) else ""
    if recurring:
        mode = get_recur_mode(task)
        if mode == "consist":
            parts.append("`t`omorrow | `#` days | `n`ext | `r` done (keep recurrence) | `del`ete | `h`elp" + journal_suffix)
        elif mode == "rand":
            parts.append("`t`omorrow | `#` days | `n`ext | `r`eset recurrence | `del`ete | `h`elp" + journal_suffix)
        else:
            interval = get_recurrence_days(task)
            if interval is not None and interval <= 7:
                parts.append("`t`omorrow | `#` days | `n`ext | `r` done (keep recurrence) | `del`ete | `h`elp" + journal_suffix)
            else:
                parts.append("`t`omorrow | `#` days | `n`ext | `r`eset recurrence | `del`ete | `h`elp" + journal_suffix)
    else:
        parts.append("`d`one | `t`omorrow | `#` days | `b`ump | `bb` big bump | `n`ext | `r`ecurring / `r N` | `h`elp" + journal_suffix)

    return "\n".join(parts)


def help_text(recurring):
    if recurring:
        return (
            "**Recurring task commands:**\n"
            "> `t` -- Move to tomorrow\n"
            "> `<number>` -- Move to *n* days from today (e.g. `15`)\n"
            "> `n` -- Skip for now, come back later\n"
            "> `r` -- **Resolve**: if `@consistrecur`, marks done; "
            "if `@randrecur`, resets to 30-50 days. "
            "Auto-assigns label if neither is set.\n"
            "> `rr` -- Tag as random recurrence (`@randrecur`)\n"
            "> `cr` -- Tag as consistent recurrence (`@consistrecur`)\n"
            "> `del` -- **Delete** the task permanently\n"
            "> `h` -- Show this help\n"
            f"> *Journal tasks:* `answer <text>` to add to {JOURNAL_FILENAME}, `n` to skip"
        )
    return (
        "**Non-recurring task commands:**\n"
        "> `d` -- Mark as done\n"
        "> `t` -- Move to tomorrow\n"
        "> `<number>` -- Move to *n* days from today (e.g. `15`)\n"
        "> `b` -- Bump due date (random 5-14 days out)\n"
        "> `bb` -- Big bump (random 15-30 days out)\n"
        "> `n` -- Skip for now, come back later\n"
        "> `r` -- Make recurring (random 30-50 days, `@randrecur`)\n"
        "> `r <N>` -- Make recurring every *N* days (`@consistrecur`)\n"
        "> `h` -- Show this help\n"
        f"> *Journal tasks:* `answer <text>` to add to {JOURNAL_FILENAME}, `n` to skip"
    )


# -- Todoist wrappers (sync -> async) -----------------------------------------

def _collect_pages(paginator):
    """Flatten a paginated Todoist result into a single list."""
    items = []
    for page in paginator:
        items.extend(page)
    return items


async def todoist_get_today():
    paginator = await asyncio.to_thread(todoist.filter_tasks, query="today | overdue | no date")
    return await asyncio.to_thread(_collect_pages, paginator)


async def todoist_close(task_id):
    await asyncio.to_thread(todoist.complete_task, task_id)


async def todoist_delete(task_id):
    await asyncio.to_thread(todoist.delete_task, task_id)


async def todoist_bump(task_id, min_days=5, max_days=14):
    days = random.randint(min_days, max_days)
    new_date = user_today() + timedelta(days=days)
    await asyncio.to_thread(todoist.update_task, task_id, due_date=new_date)
    return new_date.isoformat(), days


async def todoist_set_recurring(task_id, fixed_days=None):
    days = fixed_days if fixed_days is not None else random.randint(30, 50)
    next_due = user_today() + timedelta(days=days)
    due_string = f"every! {days} days starting {next_due.strftime('%b %d')}"
    await asyncio.to_thread(
        todoist.update_task, task_id, due_string=due_string
    )
    return days


async def todoist_set_labels(task, add_label, remove_label):
    """Add one label and remove the opposite, returning the updated label list."""
    labels = list(task.labels or [])
    if remove_label in labels:
        labels.remove(remove_label)
    if add_label not in labels:
        labels.append(add_label)
    await asyncio.to_thread(todoist.update_task, task.id, labels=labels)
    task.labels = labels
    return labels


async def todoist_update_description(task_id, description):
    """Update a task's description."""
    await asyncio.to_thread(todoist.update_task, task_id, description=description)


def _github_append_to_daily_journal_sync(repo_url, date_str, prompt, response, token):
    """Sync implementation: read file from GitHub, append entry, PUT back."""
    parsed = parse_github_repo_url(repo_url)
    if not parsed:
        raise ValueError(f"Invalid GitHub repo URL: {repo_url}")
    owner, repo = parsed
    path = JOURNAL_FILENAME
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    url_get = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    r = requests.get(url_get, headers=headers)
    if r.status_code == 404:
        content = ""
        sha = None
    elif r.status_code != 200:
        raise RuntimeError(f"GitHub GET failed: {r.status_code} {r.text[:200]}")
    else:
        data = r.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        sha = data["sha"]

    date_header = f"## {date_str}"
    if date_header not in content:
        content = content.rstrip()
        if content:
            content += "\n\n"
        content += f"{date_header}\n\n"
    content += f"### {prompt}\n{response}\n\n"

    put_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    body = {
        "message": f"Journal entry {date_str}",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        body["sha"] = sha
    r = requests.put(put_url, headers=headers, json=body)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GitHub PUT failed: {r.status_code} {r.text[:200]}")


async def append_to_daily_journal(repo_url, date_str, prompt, response):
    """Append a journal entry to the configured journal file in the given GitHub repo."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN not set")
    await asyncio.to_thread(
        _github_append_to_daily_journal_sync,
        repo_url,
        date_str,
        prompt,
        response,
        token,
    )


# -- Discord message helpers ---------------------------------------------------

async def show_task(user, session):
    """Send the current task or an 'all done' message."""
    task = session.current
    if task is None:
        await user.send("All done -- no more tasks due today!")
        sessions.pop(user.id, None)
        awaiting_repo_url.pop(user.id, None)
        return

    if session.looped:
        n = len(session.tasks)
        await user.send(
            f"Circling back to {n} skipped task{'s' if n != 1 else ''}..."
        )
        session.looped = False

    if is_journal_task(task):
        awaiting_repo_url.pop(user.id, None)
        repo_url = get_journal_repo_url(task)
        if not repo_url:
            awaiting_repo_url[user.id] = {"task": task, "session": session}
            await user.send(
                "───────────────────\n"
                f"**Journal:** {get_journal_prompt(task)}\n\n"
                "This journal task needs a GitHub repo URL. "
                "Reply with the GitHub URL (e.g. `https://github.com/you/repo`), or `skip` to skip this journal."
            )
            return
        # Journal task with URL: show normal task UI with all commands + answer
    await user.send("───────────────────\n" + format_task(task, session))


async def finish_action(user, session):
    """After a d/b/r action, advance and show next (or end)."""
    if session.advance():
        await show_task(user, session)
    else:
        await user.send("All done -- no more tasks due today!")
        sessions.pop(user.id, None)


# -- Session starter (shared by "go" command and daily nudge) ------------------

async def start_session(user):
    """Fetch today's tasks, create a session, and show the first task."""
    try:
        task_list = await todoist_get_today()
    except Exception as e:
        await user.send(f"Error fetching tasks: {e}\nSend `go` to try again.")
        return

    if not task_list:
        await user.send("No tasks due today!")
        sessions.pop(user.id, None)
        return

    random.shuffle(task_list)
    session = ReviewSession(task_list)
    sessions[user.id] = session
    count = len(task_list)
    await user.send(f"**{count}** task{'s' if count != 1 else ''} due today.")
    await show_task(user, session)


# -- Scheduled daily nudge -----------------------------------------------------

USER_TZ = ZoneInfo(TIMEZONE)
NUDGE_TIME = time(hour=NUDGE_HOUR, minute=0, tzinfo=USER_TZ)


def user_today():
    """Today's date in the user's configured timezone."""
    return datetime.now(USER_TZ).date()


@tasks.loop(time=NUDGE_TIME)
async def daily_nudge():
    try:
        user = await client.fetch_user(DISCORD_USER_ID)
        await start_session(user)
    except Exception as e:
        print(f"Daily nudge failed: {e}")


# -- Events --------------------------------------------------------------------

@client.event
async def on_ready():
    print(f"Bot ready -- logged in as {client.user} (id {client.user.id})")
    if not daily_nudge.is_running():
        daily_nudge.start()


@client.event
async def on_message(message):
    if message.author == client.user:
        return
    if not isinstance(message.channel, discord.DMChannel):
        return
    if message.author.id != DISCORD_USER_ID:
        return

    raw_text = message.content.strip()
    text = raw_text.lower()
    user = message.author

    # -- "go" starts or restarts a session --
    if text == "go":
        awaiting_repo_url.pop(user.id, None)
        await start_session(user)
        return

    # -- "answer <text>" when current task is a journal task with repo URL --
    if raw_text.lower().startswith("answer "):
        session = sessions.get(user.id)
        if session and session.current and is_journal_task(session.current):
            repo_url = get_journal_repo_url(session.current)
            if repo_url:
                response_text = raw_text[7:].strip()
                if not response_text:
                    await user.send("Reply with `answer <your response>` and some text.")
                    return
                task = session.current
                prompt = get_journal_prompt(task)
                try:
                    await append_to_daily_journal(
                        repo_url,
                        user_today().isoformat(),
                        prompt,
                        response_text,
                    )
                except Exception as e:
                    await user.send(f"Error writing to journal: {e}\nYou can try `answer <text>` again.")
                    return
                recurring = is_recurring(task)
                if recurring:
                    mode = get_recur_mode(task)
                    if mode is None:
                        interval = get_recurrence_days(task)
                        mode = "consist" if interval is not None and interval <= 7 else "rand"
                    if mode == "consist":
                        await todoist_close(task.id)
                    else:
                        await todoist_set_recurring(task.id)
                else:
                    await todoist_close(task.id)
                await user.send(f"Journal updated: **{prompt}**")
                await finish_action(user, session)
                return

    # -- When awaiting repo URL: accept URL or skip --
    if user.id in awaiting_repo_url:
        ctx = awaiting_repo_url[user.id]
        if text == "skip":
            awaiting_repo_url.pop(user.id, None)
            ctx["session"].skip()
            await show_task(user, ctx["session"])
            return
        parsed = parse_github_repo_url(raw_text)
        if parsed:
            new_desc = (ctx["task"].description or "").strip()
            repo_line = f"repo: {raw_text.strip().rstrip('/')}"
            if new_desc:
                new_desc = repo_line + "\n" + new_desc
            else:
                new_desc = repo_line
            try:
                await todoist_update_description(ctx["task"].id, new_desc)
            except Exception as e:
                await user.send(f"Error updating task: {e}")
                return
            ctx["task"].description = new_desc
            awaiting_repo_url.pop(user.id, None)
            await show_task(user, ctx["session"])
            return
        await user.send("Reply with your GitHub repo URL (e.g. https://github.com/you/repo), or `skip` to skip this journal.")
        return

    # -- "add <task>" creates a new task due today --
    if text.startswith("add "):
        task_content = raw_text[4:].strip()
        if not task_content:
            await user.send("Usage: `add <task name>`")
            return
        try:
            await asyncio.to_thread(
                todoist.add_task, content=task_content, due_date=user_today()
            )
        except Exception as e:
            await user.send(f"Error adding task: {e}")
            return
        await user.send(f"Added **{task_content}** (due today).")
        await start_session(user)
        return

    # -- Everything else requires an active session --
    session = sessions.get(user.id)
    if not session or not session.current:
        await user.send("No active session. Send `go` to start.")
        return

    task = session.current
    recurring = is_recurring(task)

    if text == "h":
        await user.send(help_text(recurring))
        return

    elif text == "d":
        if recurring:
            await user.send("Not available for recurring tasks. Try `n`, `r`, or `h`.")
            return
        try:
            await todoist_close(task.id)
        except Exception as e:
            await user.send(f"Error completing task: {e}")
            return
        await user.send(f"Done: **{task.content}**")
        await finish_action(user, session)

    elif text == "t":
        try:
            tomorrow = user_today() + timedelta(days=1)
            await asyncio.to_thread(todoist.update_task, task.id, due_date=tomorrow)
        except Exception as e:
            await user.send(f"Error moving task: {e}")
            return
        await user.send(f"Moved **{task.content}** to tomorrow ({tomorrow.isoformat()}).")
        await finish_action(user, session)

    elif text in ("b", "bb"):
        if recurring:
            await user.send("Can't bump a recurring task. Try `n`, `r`, or `h`.")
            return
        min_days, max_days = (15, 30) if text == "bb" else (5, 14)
        try:
            new_date, days = await todoist_bump(task.id, min_days, max_days)
        except Exception as e:
            await user.send(f"Error bumping task: {e}")
            return
        await user.send(f"Bumped **{task.content}** to {new_date} ({days} days out).")
        await finish_action(user, session)

    elif text == "n":
        session.skip()
        await show_task(user, session)

    elif text == "del":
        if not recurring:
            await user.send("Delete is only for recurring tasks. Use `d` to mark done instead.")
            return
        try:
            await todoist_delete(task.id)
        except Exception as e:
            await user.send(f"Error deleting task: {e}")
            return
        await user.send(f"Deleted **{task.content}** permanently.")
        await finish_action(user, session)

    elif text in ("rr", "cr"):
        if not recurring:
            await user.send("Labels only apply to recurring tasks. Try `d`, `b`, `n`, `r`, or `h`.")
            return
        if text == "rr":
            add, remove = LABEL_RAND, LABEL_CONSIST
        else:
            add, remove = LABEL_CONSIST, LABEL_RAND
        try:
            await todoist_set_labels(task, add, remove)
        except Exception as e:
            await user.send(f"Error updating labels: {e}")
            return
        await user.send(f"Labeled **{task.content}** as `@{add}`.")
        await user.send(format_task(task, session))

    elif text == "r" or re.match(r"^r\s+\d+$", text):
        r_match = re.match(r"^r\s+(\d+)$", text)
        fixed_days = int(r_match.group(1)) if r_match else None

        if recurring:
            mode = get_recur_mode(task)
            auto_assigned = None

            if mode is None:
                interval = get_recurrence_days(task)
                if interval is not None and interval <= 7:
                    mode = "consist"
                else:
                    mode = "rand"
                auto_assigned = LABEL_CONSIST if mode == "consist" else LABEL_RAND
                try:
                    await todoist_set_labels(
                        task,
                        auto_assigned,
                        LABEL_RAND if mode == "consist" else LABEL_CONSIST,
                    )
                except Exception as e:
                    await user.send(f"Error auto-assigning label: {e}")

            if mode == "consist":
                try:
                    await todoist_close(task.id)
                except Exception as e:
                    await user.send(f"Error completing task: {e}")
                    return
                msg = f"Completed **{task.content}** (kept recurrence as-is)."
                if auto_assigned:
                    msg += f" Auto-tagged `@{auto_assigned}`."
                await user.send(msg)
            else:
                try:
                    days = await todoist_set_recurring(task.id, fixed_days=fixed_days)
                except Exception as e:
                    await user.send(f"Error updating task: {e}")
                    return
                if fixed_days:
                    try:
                        await todoist_set_labels(task, LABEL_CONSIST, LABEL_RAND)
                    except Exception as e:
                        await user.send(f"Error updating label: {e}")
                    msg = f"Reset **{task.content}** to every {days} days. Switched to `@{LABEL_CONSIST}`."
                else:
                    msg = f"Reset **{task.content}** to every {days} days."
                    if auto_assigned:
                        msg += f" Auto-tagged `@{auto_assigned}`."
                await user.send(msg)
        else:
            try:
                days = await todoist_set_recurring(task.id, fixed_days=fixed_days)
            except Exception as e:
                await user.send(f"Error updating task: {e}")
                return
            if fixed_days:
                label = LABEL_CONSIST
            else:
                label = LABEL_RAND
            try:
                await todoist_set_labels(task, label, LABEL_CONSIST if label == LABEL_RAND else LABEL_RAND)
            except Exception as e:
                await user.send(f"Error setting label: {e}")
            await user.send(f"Made **{task.content}** recurring: every {days} days. Tagged `@{label}`.")
        await finish_action(user, session)

    elif text.isdigit():
        days = int(text)
        if days == 0:
            await user.send("Enter a number greater than 0.")
            return
        try:
            new_date = user_today() + timedelta(days=days)
            await asyncio.to_thread(todoist.update_task, task.id, due_date=new_date)
        except Exception as e:
            await user.send(f"Error updating due date: {e}")
            return
        await user.send(f"Moved **{task.content}** to {new_date.isoformat()} ({days} day{'s' if days != 1 else ''} out).")
        await finish_action(user, session)

    else:
        await user.send(
            f"Unknown command: `{text}`\nSend `h` for help or `go` to start over."
        )


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
