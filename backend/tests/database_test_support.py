"""Isolated SQLite fixture for FastAPI tests that enter the app lifespan."""

import tempfile
import unittest
from pathlib import Path

from app.database.instance import repository


class IsolatedDatabaseTestCase(unittest.TestCase):
    """Keep integration-test migrations and rows away from developer data."""

    def setUp(self) -> None:
        super().setUp()
        self._database_directory = tempfile.TemporaryDirectory()
        original_path = repository.database_path
        repository.database_path = Path(self._database_directory.name) / "test.sqlite3"
        # Cleanups execute last-in, first-out: restore the path before deleting
        # the temporary directory, including when a test fails or is skipped.
        self.addCleanup(self._database_directory.cleanup)
        self.addCleanup(setattr, repository, "database_path", original_path)
