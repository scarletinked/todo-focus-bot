import sys
import os
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure the project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@dataclass
class FakeDue:
    string: str = ""
    is_recurring: bool = False


@dataclass
class FakeTask:
    id: str = "123"
    content: str = "Test task"
    description: str = ""
    labels: list = field(default_factory=list)
    due: FakeDue = None


def make_task(content="Test task", *, due_string=None, recurring=False,
              labels=None, description="", task_id="123"):
    """Convenience factory for building fake tasks."""
    due = None
    if due_string is not None or recurring:
        due = FakeDue(string=due_string or "", is_recurring=recurring)
    return FakeTask(
        id=task_id,
        content=content,
        description=description,
        labels=labels or [],
        due=due,
    )


@pytest.fixture
def fake_user():
    """A mock Discord user with an async .send() and a numeric .id."""
    user = MagicMock()
    user.id = 12345
    user.send = AsyncMock()
    return user
