import pytest
from conftest import make_task, FakeDue
from bot import (
    is_recurring,
    get_recur_mode,
    get_recurrence_days,
    format_task,
    help_text,
    ReviewSession,
)


# -- is_recurring --------------------------------------------------------------

class TestIsRecurring:
    def test_recurring_task(self):
        t = make_task(due_string="every day", recurring=True)
        assert is_recurring(t) is True

    def test_non_recurring_task(self):
        t = make_task(due_string="2025-03-01", recurring=False)
        assert is_recurring(t) is False

    def test_no_due_date(self):
        t = make_task()
        assert is_recurring(t) is False


# -- get_recur_mode ------------------------------------------------------------

class TestGetRecurMode:
    def test_rand_label(self):
        t = make_task(labels=["randrecur"])
        assert get_recur_mode(t) == "rand"

    def test_consist_label(self):
        t = make_task(labels=["consistrecur"])
        assert get_recur_mode(t) == "consist"

    def test_no_label(self):
        t = make_task(labels=[])
        assert get_recur_mode(t) is None

    def test_rand_takes_precedence_over_consist(self):
        t = make_task(labels=["randrecur", "consistrecur"])
        assert get_recur_mode(t) == "rand"

    def test_unrelated_labels_ignored(self):
        t = make_task(labels=["priority", "work"])
        assert get_recur_mode(t) is None


# -- get_recurrence_days -------------------------------------------------------

class TestGetRecurrenceDays:
    @pytest.mark.parametrize("due_string, expected", [
        ("every day", 1),
        ("every! day", 1),
        ("every other day", 2),
        ("every! other day", 2),
        ("every 3 days", 3),
        ("every! 10 days", 10),
        ("every 1 day", 1),
        ("every week", 7),
        ("every! week", 7),
        ("every other week", 14),
        ("every 2 weeks", 14),
        ("every! 3 weeks", 21),
        ("every month", 30),
        ("every! month", 30),
        ("every other month", 60),
        ("every 2 months", 60),
        ("every! 6 months", 180),
        ("every monday", 7),
        ("every! Friday", 7),
        ("every wed", 7),
        ("every Saturday", 7),
    ])
    def test_known_patterns(self, due_string, expected):
        t = make_task(due_string=due_string, recurring=True)
        assert get_recurrence_days(t) == expected

    def test_no_due(self):
        t = make_task()
        assert get_recurrence_days(t) is None

    def test_empty_string(self):
        t = make_task(due_string="", recurring=True)
        assert get_recurrence_days(t) is None

    def test_unrecognized_pattern(self):
        t = make_task(due_string="every third full moon", recurring=True)
        assert get_recurrence_days(t) is None


# -- format_task ---------------------------------------------------------------

class TestFormatTask:
    def test_non_recurring_basic(self):
        t = make_task("Buy milk")
        s = ReviewSession([t])
        out = format_task(t, s)
        assert "**Buy milk**" in out
        assert "1 remaining" in out
        assert "`d`one" in out

    def test_non_recurring_with_description(self):
        t = make_task("Buy milk", description="Get 2%")
        s = ReviewSession([t])
        out = format_task(t, s)
        assert "> Get 2%" in out

    def test_recurring_with_known_interval(self):
        t = make_task("Exercise", due_string="every 3 days", recurring=True)
        s = ReviewSession([t])
        out = format_task(t, s)
        assert "(every 3d)" in out
        assert "`d`one" not in out

    def test_recurring_with_unknown_interval(self):
        t = make_task("Weird", due_string="every blue moon", recurring=True)
        s = ReviewSession([t])
        out = format_task(t, s)
        assert "(recurring: every blue moon)" in out

    def test_skipped_count_shown(self):
        t1 = make_task("A")
        t2 = make_task("B")
        s = ReviewSession([t1, t2])
        s.skip()
        out = format_task(s.current, s)
        assert "1 skipped" in out

    def test_consist_label_shows_keep_recurrence(self):
        t = make_task("Daily", due_string="every day", recurring=True,
                      labels=["consistrecur"])
        s = ReviewSession([t])
        out = format_task(t, s)
        assert "keep recurrence" in out

    def test_rand_label_shows_reset(self):
        t = make_task("Random", due_string="every 30 days", recurring=True,
                      labels=["randrecur"])
        s = ReviewSession([t])
        out = format_task(t, s)
        assert "`r`eset recurrence" in out


# -- help_text -----------------------------------------------------------------

class TestHelpText:
    def test_recurring_help_contains_key_commands(self):
        text = help_text(recurring=True)
        assert "`t`" in text
        assert "`n`" in text
        assert "`r`" in text
        assert "`rr`" in text
        assert "`cr`" in text
        assert "`<number>`" in text

    def test_non_recurring_help_contains_key_commands(self):
        text = help_text(recurring=False)
        assert "`d`" in text
        assert "`t`" in text
        assert "`b`" in text
        assert "`bb`" in text
        assert "`n`" in text
        assert "`r`" in text
        assert "`<number>`" in text
