"""Shared fixtures for pkgdb tests."""

import ipaddress
import json
import socket
import tempfile
from pathlib import Path

import pytest

from pkgdb import get_db_connection, init_db

# Hostnames that resolve to this machine and so never leave it.
_LOCAL_HOSTS = frozenset({"localhost", "localhost.localdomain", ""})


def _is_local(address) -> bool:
    """Return True if `address` is loopback, unspecified, or a non-IP family.

    Non-tuple addresses belong to families like AF_UNIX that cannot reach the
    network, so they are always allowed.
    """
    if not isinstance(address, (tuple, list)) or not address:
        return True
    host = address[0]
    if not isinstance(host, str):
        return True
    if host.lower() in _LOCAL_HOSTS:
        return True
    try:
        ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return ip.is_loopback or ip.is_unspecified


@pytest.fixture(autouse=True)
def block_network(request, monkeypatch):
    """Fail any test that opens a connection beyond this machine.

    Live API calls make tests non-deterministic: they pass locally and then
    fail in CI when the upstream service rate-limits the runner. Blocking them
    turns a missing mock into an immediate, obvious error instead.

    Tests marked `integration` are exempt, since making real API calls is
    their whole purpose. Loopback is always allowed so the HTTP server tests
    keep working.
    """
    if request.node.get_closest_marker("integration"):
        return

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create_connection = socket.create_connection

    def guard(address):
        if not _is_local(address):
            raise RuntimeError(
                f"Blocked network connection to {address!r} in "
                f"{request.node.nodeid}. Mock the API call, or mark the test "
                f"'integration' if it is meant to hit the real service."
            )

    def connect(self, address):
        guard(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        guard(address)
        return real_connect_ex(self, address)

    def create_connection(address, *args, **kwargs):
        guard(address)
        return real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "create_connection", create_connection)


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
