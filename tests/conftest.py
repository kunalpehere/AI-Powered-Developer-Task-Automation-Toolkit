import pytest

from taskmaster.database import Database
from taskmaster.organizer import FileOrganizer


@pytest.fixture
def organizer(tmp_path):
    instance = FileOrganizer(Database(str(tmp_path / "test.sqlite")))
    try:
        yield instance
    finally:
        instance.close()
