# SPDX-License-Identifier: MIT
"""SQLite package-existence filter over pypi.db / conda.db.

The databases ship a single table ``packages(name TEXT, source TEXT)`` plus a
``metadata(key, value)`` table. We only need exact-case existence checks
(matching the JS extension's ``SELECT name FROM packages WHERE name = ? LIMIT 1``).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Literal

from helpip_cli import config
from helpip_cli.storage import Storage

DbKind = Literal["pypi", "conda"]

_DB_NAMES: dict[DbKind, str] = {"pypi": config.PYPI_DB, "conda": config.CONDA_DB}


class PackageDb:
    def __init__(self, storage: Storage) -> None:
        self._storage = storage
        self._conns: dict[DbKind, sqlite3.Connection] = {}

    def _conn(self, kind: DbKind) -> sqlite3.Connection:
        conn = self._conns.get(kind)
        if conn is not None:
            return conn
        path = self._storage.path(_DB_NAMES[kind])
        # Read-only, cross-thread safe enough for a short-lived CLI.
        conn = sqlite3.connect(
            "file:{}?mode=ro".format(path), uri=True, check_same_thread=False
        )
        self._conns[kind] = conn
        return conn

    def strict_match(self, kind: DbKind, name: str) -> bool:
        """Exact-case existence check (no normalization)."""
        try:
            cur = self._conn(kind).execute(
                "SELECT name FROM packages WHERE name = ? LIMIT 1", (name,)
            )
        except sqlite3.DatabaseError:
            return False
        try:
            return cur.fetchone() is not None
        finally:
            cur.close()

    def package_exists(self, kind: DbKind, name: str) -> bool:
        return self.strict_match(kind, name)

    def last_update(self, kind: DbKind) -> str | None:
        try:
            cur = self._conn(kind).execute(
                "SELECT value FROM metadata WHERE key = 'last_update' LIMIT 1"
            )
        except sqlite3.DatabaseError:
            return None
        try:
            row = cur.fetchone()
            return row[0] if row else None
        finally:
            cur.close()

    def close(self) -> None:
        for conn in self._conns.values():
            conn.close()
        self._conns.clear()
