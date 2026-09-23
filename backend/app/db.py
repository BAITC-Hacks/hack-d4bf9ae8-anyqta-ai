"""SQLite connection and migration helpers for Career Quest."""

from __future__ import annotations

import sqlite3
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def connect(database_path: str | Path) -> sqlite3.Connection:
    """Open a database with foreign-key validation enabled."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def migrate(connection: sqlite3.Connection) -> None:
    """Apply each numbered SQL migration exactly once."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    applied = {
        row["version"]
        for row in connection.execute("SELECT version FROM schema_migrations")
    }
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if migration.name in applied:
            continue
        with connection:
            connection.executescript(migration.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)", (migration.name,)
            )
