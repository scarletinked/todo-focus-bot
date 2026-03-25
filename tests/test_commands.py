import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import pytest_asyncio

import bot
from conftest import make_task


@pytest.fixture(autouse=True)
def clear_sessions():
    """Ensure sessions dict is clean for every test."""
    bot.sessions.clear()
    yield
    bot.sessions.clear()


@pytest.fixture
def user():
    user = MagicMock()
    user.id = bot.DISCORD_USER_ID
    user.send = AsyncMock()
    return user


def _make_message(user, text):
    msg = MagicMock()
    msg.author = user
    msg.content = text
    msg.channel = MagicMock(spec=discord.DMChannel)
    return msg


def _sent_texts(user):
    """Return a list of all string args passed to user.send()."""
    return [call.args[0] for call in user.send.call_args_list]


# -- "go" command --------------------------------------------------------------

class TestGoCommand:
    @pytest.mark.asyncio
    @patch("bot.todoist_get_today", new_callable=AsyncMock)
    async def test_go_starts_session(self, mock_get, user):
        mock_get.return_value = [make_task("A"), make_task("B")]
        await bot.on_message(_make_message(user, "go"))

        assert user.id in bot.sessions
        texts = _sent_texts(user)
        assert any("2" in t and "task" in t for t in texts)

    @pytest.mark.asyncio
    @patch("bot.todoist_get_today", new_callable=AsyncMock)
    async def test_go_no_tasks(self, mock_get, user):
        mock_get.return_value = []
        await bot.on_message(_make_message(user, "go"))

        texts = _sent_texts(user)
        assert any("No tasks" in t for t in texts)
        assert user.id not in bot.sessions

    @pytest.mark.asyncio
    @patch("bot.todoist_get_today", new_callable=AsyncMock)
    async def test_go_api_error(self, mock_get, user):
        mock_get.side_effect = Exception("API down")
        await bot.on_message(_make_message(user, "go"))

        texts = _sent_texts(user)
        assert any("Error" in t for t in texts)


# -- "add" command -------------------------------------------------------------

class TestAddCommand:
    @pytest.mark.asyncio
    @patch("bot.todoist_get_today", new_callable=AsyncMock)
    @patch("bot.asyncio.to_thread", new_callable=AsyncMock)
    async def test_add_creates_task_and_starts_session(self, mock_thread, mock_get, user):
        new_task = make_task("Buy groceries")
        mock_get.return_value = [new_task]

        await bot.on_message(_make_message(user, "add Buy groceries"))

        mock_thread.assert_called_once()
        call_args = mock_thread.call_args
        assert call_args.kwargs["content"] == "Buy groceries"
        assert call_args.kwargs["due_date"] == date.today()

        texts = _sent_texts(user)
        assert any("Added" in t and "Buy groceries" in t for t in texts)
        assert user.id in bot.sessions

    @pytest.mark.asyncio
    @patch("bot.todoist_get_today", new_callable=AsyncMock)
    @patch("bot.asyncio.to_thread", new_callable=AsyncMock)
    async def test_add_preserves_case(self, mock_thread, mock_get, user):
        mock_get.return_value = [make_task("Fix The Bug")]
        await bot.on_message(_make_message(user, "ADD Fix The Bug"))

        call_args = mock_thread.call_args
        assert call_args.kwargs["content"] == "Fix The Bug"

    @pytest.mark.asyncio
    @patch("bot.todoist_get_today", new_callable=AsyncMock)
    async def test_add_refreshes_session(self, mock_get, user):
        """add starts a fresh session after creating the task."""
        assert user.id not in bot.sessions
        mock_get.return_value = [make_task("Something")]
        with patch("bot.asyncio.to_thread", new_callable=AsyncMock):
            await bot.on_message(_make_message(user, "add Something"))
        texts = _sent_texts(user)
        assert any("Added" in t for t in texts)
        assert any("1" in t and "task" in t for t in texts)


# -- "d" (done) command --------------------------------------------------------

class TestDoneCommand:
    @pytest.mark.asyncio
    @patch("bot.todoist_close", new_callable=AsyncMock)
    async def test_done_completes_task(self, mock_close, user):
        task = make_task("Finish report")
        session = bot.ReviewSession([task])
        bot.sessions[user.id] = session

        await bot.on_message(_make_message(user, "d"))

        mock_close.assert_called_once_with("123")
        texts = _sent_texts(user)
        assert any("Done" in t and "Finish report" in t for t in texts)

    @pytest.mark.asyncio
    async def test_done_blocked_for_recurring(self, user):
        task = make_task("Daily", due_string="every day", recurring=True)
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "d"))

        texts = _sent_texts(user)
        assert any("Not available" in t for t in texts)


# -- "t" (tomorrow) command ----------------------------------------------------

class TestTomorrowCommand:
    @pytest.mark.asyncio
    @patch("bot.asyncio.to_thread", new_callable=AsyncMock)
    async def test_tomorrow_updates_due(self, mock_thread, user):
        task = make_task("Read book")
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "t"))

        mock_thread.assert_called_once()
        texts = _sent_texts(user)
        tomorrow = date.today() + timedelta(days=1)
        assert any(tomorrow.isoformat() in t for t in texts)


# -- "b" / "bb" (bump) command ------------------------------------------------

class TestBumpCommand:
    @pytest.mark.asyncio
    @patch("bot.todoist_bump", new_callable=AsyncMock)
    async def test_bump(self, mock_bump, user):
        mock_bump.return_value = ("2026-03-10", 7)
        task = make_task("Clean garage")
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "b"))

        mock_bump.assert_called_once_with("123", 5, 14)
        texts = _sent_texts(user)
        assert any("Bumped" in t for t in texts)

    @pytest.mark.asyncio
    @patch("bot.todoist_bump", new_callable=AsyncMock)
    async def test_big_bump(self, mock_bump, user):
        mock_bump.return_value = ("2026-04-01", 20)
        task = make_task("Reorganize files")
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "bb"))

        mock_bump.assert_called_once_with("123", 15, 30)

    @pytest.mark.asyncio
    async def test_bump_blocked_for_recurring(self, user):
        task = make_task("Daily", due_string="every day", recurring=True)
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "b"))

        texts = _sent_texts(user)
        assert any("Can't bump" in t for t in texts)


# -- "n" (next/skip) command ---------------------------------------------------

class TestNextCommand:
    @pytest.mark.asyncio
    async def test_skip_advances(self, user):
        t1 = make_task("A")
        t2 = make_task("B")
        bot.sessions[user.id] = bot.ReviewSession([t1, t2])

        await bot.on_message(_make_message(user, "n"))

        session = bot.sessions[user.id]
        assert session.current.content == "B"


# -- numeric days command ------------------------------------------------------

class TestNumericCommand:
    @pytest.mark.asyncio
    @patch("bot.asyncio.to_thread", new_callable=AsyncMock)
    async def test_numeric_sets_due_date(self, mock_thread, user):
        task = make_task("Plan trip")
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "15"))

        expected_date = date.today() + timedelta(days=15)
        mock_thread.assert_called_once()
        texts = _sent_texts(user)
        assert any(expected_date.isoformat() in t for t in texts)
        assert any("15 days" in t for t in texts)

    @pytest.mark.asyncio
    async def test_zero_rejected(self, user):
        task = make_task("Nope")
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "0"))

        texts = _sent_texts(user)
        assert any("greater than 0" in t for t in texts)

    @pytest.mark.asyncio
    @patch("bot.asyncio.to_thread", new_callable=AsyncMock)
    async def test_single_day(self, mock_thread, user):
        task = make_task("Soon")
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "1"))

        texts = _sent_texts(user)
        assert any("1 day out" in t for t in texts)


# -- "h" (help) command --------------------------------------------------------

class TestHelpCommand:
    @pytest.mark.asyncio
    async def test_help_non_recurring(self, user):
        task = make_task("Normal task")
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "h"))

        texts = _sent_texts(user)
        assert any("Non-recurring" in t for t in texts)

    @pytest.mark.asyncio
    async def test_help_recurring(self, user):
        task = make_task("Repeater", due_string="every day", recurring=True)
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "h"))

        texts = _sent_texts(user)
        assert any("Recurring" in t for t in texts)


# -- "rr" / "cr" label commands ------------------------------------------------

class TestLabelCommands:
    @pytest.mark.asyncio
    @patch("bot.todoist_set_labels", new_callable=AsyncMock)
    async def test_rr_sets_rand_label(self, mock_labels, user):
        task = make_task("Recurring", due_string="every 30 days", recurring=True)
        mock_labels.return_value = ["randrecur"]
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "rr"))

        mock_labels.assert_called_once_with(task, "randrecur", "consistrecur")
        texts = _sent_texts(user)
        assert any("@randrecur" in t for t in texts)

    @pytest.mark.asyncio
    @patch("bot.todoist_set_labels", new_callable=AsyncMock)
    async def test_cr_sets_consist_label(self, mock_labels, user):
        task = make_task("Recurring", due_string="every day", recurring=True)
        mock_labels.return_value = ["consistrecur"]
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "cr"))

        mock_labels.assert_called_once_with(task, "consistrecur", "randrecur")

    @pytest.mark.asyncio
    async def test_labels_blocked_for_non_recurring(self, user):
        task = make_task("One-off")
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "rr"))

        texts = _sent_texts(user)
        assert any("Labels only apply" in t for t in texts)


# -- "r" (resolve) command -----------------------------------------------------

class TestResolveCommand:
    @pytest.mark.asyncio
    @patch("bot.todoist_close", new_callable=AsyncMock)
    @patch("bot.todoist_set_labels", new_callable=AsyncMock)
    async def test_r_consist_completes(self, mock_labels, mock_close, user):
        task = make_task("Daily jog", due_string="every day", recurring=True,
                         labels=["consistrecur"])
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "r"))

        mock_close.assert_called_once_with("123")
        texts = _sent_texts(user)
        assert any("Completed" in t for t in texts)

    @pytest.mark.asyncio
    @patch("bot.todoist_set_recurring", new_callable=AsyncMock)
    async def test_r_rand_resets(self, mock_recur, user):
        mock_recur.return_value = 42
        task = make_task("Random check", due_string="every 40 days", recurring=True,
                         labels=["randrecur"])
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "r"))

        mock_recur.assert_called_once_with("123")
        texts = _sent_texts(user)
        assert any("Reset" in t and "42 days" in t for t in texts)

    @pytest.mark.asyncio
    @patch("bot.todoist_set_labels", new_callable=AsyncMock)
    @patch("bot.todoist_set_recurring", new_callable=AsyncMock)
    async def test_r_non_recurring_random(self, mock_recur, mock_labels, user):
        mock_recur.return_value = 35
        task = make_task("One-off task")
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "r"))

        mock_recur.assert_called_once_with("123", fixed_days=None)
        mock_labels.assert_called_once_with(task, "randrecur", "consistrecur")
        texts = _sent_texts(user)
        assert any("recurring" in t.lower() and "35 days" in t for t in texts)
        assert any("@randrecur" in t for t in texts)

    @pytest.mark.asyncio
    @patch("bot.todoist_set_labels", new_callable=AsyncMock)
    @patch("bot.todoist_set_recurring", new_callable=AsyncMock)
    async def test_r_with_days_non_recurring_consistent(self, mock_recur, mock_labels, user):
        mock_recur.return_value = 14
        task = make_task("One-off task")
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "r 14"))

        mock_recur.assert_called_once_with("123", fixed_days=14)
        mock_labels.assert_called_once_with(task, "consistrecur", "randrecur")
        texts = _sent_texts(user)
        assert any("recurring" in t.lower() and "14 days" in t for t in texts)
        assert any("@consistrecur" in t for t in texts)

    @pytest.mark.asyncio
    @patch("bot.todoist_set_labels", new_callable=AsyncMock)
    @patch("bot.todoist_set_recurring", new_callable=AsyncMock)
    async def test_r_with_days_rand_recurring_switches_to_consist(self, mock_recur, mock_labels, user):
        mock_recur.return_value = 7
        task = make_task("Random check", due_string="every 45 days", recurring=True,
                         labels=["randrecur"])
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "r 7"))

        mock_recur.assert_called_once_with("123", fixed_days=7)
        mock_labels.assert_called_once_with(task, "consistrecur", "randrecur")
        texts = _sent_texts(user)
        assert any("7 days" in t for t in texts)
        assert any("@consistrecur" in t for t in texts)


# -- unknown command -----------------------------------------------------------

class TestUnknownCommand:
    @pytest.mark.asyncio
    async def test_unknown(self, user):
        task = make_task("Anything")
        bot.sessions[user.id] = bot.ReviewSession([task])

        await bot.on_message(_make_message(user, "xyz"))

        texts = _sent_texts(user)
        assert any("Unknown command" in t for t in texts)


# -- no active session ---------------------------------------------------------

class TestNoSession:
    @pytest.mark.asyncio
    async def test_command_without_session(self, user):
        await bot.on_message(_make_message(user, "d"))

        texts = _sent_texts(user)
        assert any("No active session" in t for t in texts)


# -- messages from wrong user / non-DM are ignored ----------------------------

class TestMessageFiltering:
    @pytest.mark.asyncio
    async def test_non_dm_ignored(self, user):
        msg = _make_message(user, "go")
        msg.channel = MagicMock()  # not a DMChannel
        await bot.on_message(msg)
        user.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_wrong_user_ignored(self):
        wrong_user = MagicMock()
        wrong_user.id = 99999
        wrong_user.send = AsyncMock()
        msg = _make_message(wrong_user, "go")
        await bot.on_message(msg)
        wrong_user.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_own_message_ignored(self, user):
        msg = _make_message(user, "go")
        msg.author = bot.client.user
        await bot.on_message(msg)
        user.send.assert_not_called()
