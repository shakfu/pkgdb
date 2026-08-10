"""Shared fixtures for pkgdb tests."""

import json
import tempfile
from pathlib import Path

import pytest

from pkgdb import get_db_connection, init_db


def track(conn, *package_names, added_date="2024-01-01"):
    """Register packages in the `packages` table.

    Tests that seed `package_stats` directly still need their packages listed
    as tracked, because tracked-package views (show, report, export, history)
    filter on `packages` so that removed packages stop appearing before
    `cleanup` physically purges their retained rows.
    """
    for name in package_names:
        conn.execute(
            "INSERT OR IGNORE INTO packages (package_name, added_date) VALUES (?, ?)",
            (name, added_date),
        )
    conn.commit()


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def temp_packages_file():
    """Create a temporary packages.json file."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump({"published": ["package-a", "package-b"]}, f)
        packages_path = f.name
    yield packages_path
    Path(packages_path).unlink(missing_ok=True)


@pytest.fixture
def db_conn(temp_db):
    """Create an initialized database connection."""
    conn = get_db_connection(temp_db)
    init_db(conn)
    yield conn
    conn.close()
