"""Tests for pkgdb backup and restore."""

import sqlite3
from unittest.mock import patch

import pytest

from pkgdb import (
    PackageStatsService,
    add_package,
    get_db_connection,
    get_packages,
    init_db,
)
from pkgdb.cli import main
from pkgdb.db import backup_database, restore_database


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "pkg.db")
    conn = get_db_connection(path)
    init_db(conn)
    add_package(conn, "original")
    conn.close()
    return path


def packages(path):
    conn = get_db_connection(path)
    try:
        return get_packages(conn)
    finally:
        conn.close()


def run_cli(db_path, *argv):
    with patch("sys.argv", ["pkgdb", "-d", db_path, *argv]):
        main()


def test_backup_then_restore_recovers_data(db, tmp_path):
    dest = str(tmp_path / "backup.db")
    backup_database(db, dest)

    conn = get_db_connection(db)
    add_package(conn, "added-later")
    conn.close()

    kept = restore_database(db, dest)

    assert packages(db) == ["original"]
    assert sorted(packages(kept)) == ["added-later", "original"]


def test_backup_refuses_overwrite_without_force(db, tmp_path):
    dest = tmp_path / "backup.db"
    dest.write_text("precious")

    with pytest.raises(FileExistsError):
        backup_database(db, str(dest))
    assert dest.read_text() == "precious"

    backup_database(db, str(dest), force=True)
    assert packages(str(dest)) == ["original"]


def test_backup_rejects_itself_as_destination(db):
    with pytest.raises(ValueError):
        backup_database(db, db, force=True)
    assert packages(db) == ["original"]


def test_backup_missing_database_creates_nothing(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(ValueError):
        backup_database(str(missing), str(tmp_path / "backup.db"))
    assert not missing.exists()
    assert not (tmp_path / "backup.db").exists()


@pytest.mark.parametrize("content", [b"", b"not a database" * 200])
def test_restore_rejects_invalid_backup(db, tmp_path, content):
    bad = tmp_path / "bad.db"
    bad.write_bytes(content)

    with pytest.raises(ValueError):
        restore_database(db, str(bad))

    assert packages(db) == ["original"]
    assert not list(tmp_path.glob("*.pre-restore-*"))


def test_restore_rejects_foreign_sqlite_file(db, tmp_path):
    foreign = tmp_path / "foreign.db"
    conn = sqlite3.connect(foreign)
    conn.execute("CREATE TABLE other (x)")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="not a pkgdb database"):
        restore_database(db, str(foreign))


def test_restore_over_corrupt_database_keeps_it(db, tmp_path):
    dest = str(tmp_path / "backup.db")
    backup_database(db, dest)
    with open(db, "wb") as f:
        f.write(b"corrupt" * 1000)

    kept = restore_database(db, dest)

    assert packages(db) == ["original"]
    with open(kept, "rb") as f:
        assert f.read().startswith(b"corrupt")


def test_restore_without_existing_database(db, tmp_path):
    target = str(tmp_path / "new.db")
    assert restore_database(target, db) is None
    assert packages(target) == ["original"]


def test_restored_old_schema_is_migrated_on_open(db, tmp_path):
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    conn.execute(
        "CREATE TABLE packages (package_name TEXT PRIMARY KEY, added_date TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO packages VALUES ('legacy', '2020-01-01')")
    conn.commit()
    conn.close()

    restore_database(db, str(old))

    service = PackageStatsService(db)
    assert service.add_tag("legacy", "web")
    assert service.get_package_tags("legacy") == ["web"]


def test_cli_backup_default_path_and_restore(db, tmp_path):
    run_cli(db, "backup")
    backups = list(tmp_path.glob("pkg.db.*.bak"))
    assert len(backups) == 1

    conn = get_db_connection(db)
    add_package(conn, "added-later")
    conn.close()

    run_cli(db, "restore", str(backups[0]))
    assert packages(db) == ["original"]


def test_cli_restore_failure_exits_nonzero(db, tmp_path, caplog):
    with pytest.raises(SystemExit) as exc:
        run_cli(db, "restore", str(tmp_path / "missing.db"))
    assert exc.value.code == 1
    assert "Restore failed" in caplog.text
