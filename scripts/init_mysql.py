#!/usr/bin/env python3
"""Create the MySQL databases referenced by the stack's env URLs.

SQLite URLs are skipped so the script is a no-op for the old configuration.
Runs inside the Superset image, which ships PyMySQL.
"""

from __future__ import annotations

import os
from urllib.parse import unquote, urlsplit

import pymysql

URL_VARS = ("SUPERSET_METADATA_URI", "DEMO_DB_URI", "ADMIN_DB_URL")


def main() -> int:
    ensured: set[str] = set()
    for variable in URL_VARS:
        url = os.environ.get(variable, "")
        parts = urlsplit(url)
        if parts.scheme not in {"mysql", "mysql+pymysql"}:
            continue
        database = parts.path.lstrip("/")
        if not database:
            raise SystemExit(f"{variable} has no database name")
        if database in ensured:
            continue
        connection = pymysql.connect(
            host=parts.hostname or "127.0.0.1",
            port=parts.port or 3306,
            user=unquote(parts.username or "root"),
            password=unquote(parts.password or ""),
            charset="utf8mb4",
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            connection.commit()
        finally:
            connection.close()
        ensured.add(database)
        print(f"[mysql] ensured database {database}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
