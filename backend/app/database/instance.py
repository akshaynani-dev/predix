"""Shared repository instance used by API and application lifecycle."""

from app.core.config import settings
from app.database.sqlite_repository import SQLiteRepository

repository = SQLiteRepository(settings.database_path)
