from conftest import make_task
from bot import ReviewSession


class TestReviewSessionBasics:
    def test_current_returns_first_task(self):
        tasks = [make_task("A"), make_task("B"), make_task("C")]
        s = ReviewSession(tasks)
        assert s.current.content == "A"

    def test_remaining_starts_at_total(self):
        s = ReviewSession([make_task("A"), make_task("B")])
        assert s.remaining == 2

    def test_advance_moves_to_next(self):
        s = ReviewSession([make_task("A"), make_task("B")])
        assert s.advance() is True
        assert s.current.content == "B"
        assert s.remaining == 1

    def test_advance_past_last_returns_false(self):
        s = ReviewSession([make_task("A")])
        assert s.advance() is False

    def test_current_is_none_after_exhausted(self):
        s = ReviewSession([make_task("A")])
        s.advance()
        assert s.current is None
        assert s.remaining == 0

    def test_empty_session(self):
        s = ReviewSession([])
        assert s.current is None
        assert s.remaining == 0
        assert s.advance() is False


class TestReviewSessionSkip:
    def test_skip_adds_to_skipped_and_advances(self):
        s = ReviewSession([make_task("A"), make_task("B")])
        s.skip()
        assert s.current.content == "B"
        assert len(s.skipped) == 1
        assert s.skipped[0].content == "A"

    def test_skip_all_loops_back(self):
        s = ReviewSession([make_task("A"), make_task("B")])
        s.skip()  # skip A, now on B
        s.skip()  # skip B, loops back
        assert s.looped is True
        assert s.current.content == "A"
        assert s.remaining == 2

    def test_looped_flag_only_set_once(self):
        s = ReviewSession([make_task("A")])
        s.skip()  # skip A, loops back to A
        assert s.looped is True
        s.looped = False
        s.advance()  # exhaust
        assert s.looped is False

    def test_skip_single_task_loops(self):
        s = ReviewSession([make_task("A")])
        result = s.skip()
        assert result is True
        assert s.looped is True
        assert s.current.content == "A"

    def test_mixed_advance_and_skip(self):
        s = ReviewSession([make_task("A"), make_task("B"), make_task("C")])
        s.advance()   # done with A, now on B
        s.skip()      # skip B, now on C
        s.advance()   # done with C, loops back to [B]
        assert s.looped is True
        assert s.current.content == "B"
        assert s.remaining == 1
