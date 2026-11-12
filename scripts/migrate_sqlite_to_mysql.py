#!/usr/bin/env python3
"""Copy every table from a SQLite database into an already-created MySQL schema.

The MySQL schema is expected to come from the application itself (Superset
`db upgrade` or the agent's `ensure_schema`); this script only moves rows,
preserving primary keys and foreign-key targets. `--truncate` allows a retry
against a partially loaded target.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from urllib.parse import unquote, urlsplit

import pymysql

SKIP_TABLES = {"sqlite_sequence", "alembic_version"}


def mysql_options(url: str) -> dict:
    parts = urlsplit(url)
    if parts.scheme not in {"mysql", "mysql+pymysql"}:
        raise SystemExit(f"expected mysql+pymysql URL, got {parts.scheme}")
    database = parts.path.lstrip("/")
    if not database:
        raise SystemExit("MySQL URL has no database name")
    return {
        "host": parts.hostname or "127.0.0.1",
        "port": parts.port or 3306,
        "user": unquote(parts.username or "root"),
        "password": unquote(parts.password or ""),
        "database": database,
        "charset": "utf8mb4",
    }


def quote(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", required=True)
    parser.add_argument("--mysql-url", required=True)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--truncate", action="store_true")
    args = parser.parse_args()

    source = sqlite3.connect(f"file:{args.sqlite}?mode=ro", uri=True)
    target = pymysql.connect(**mysql_options(args.mysql_url), autocommit=False)
    database = target.db.decode() if isinstance(target.db, bytes) else target.db

    with target.cursor() as cursor:
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        cursor.execute(
            "SELECT table_name, column_name, data_type, is_nullable, "
            "column_default, extra FROM information_schema.columns "
            "WHERE table_schema = %s ORDER BY table_name, ordinal_position",
            (database,),
        )
        target_columns: dict[str, list[dict]] = {}
        for table, column, data_type, nullable, default, extra in cursor.fetchall():
            target_columns.setdefault(table, []).append(
                {
                    "name": column,
                    "type": data_type,
                    "nullable": nullable == "YES",
                    "default": default,
                    "extra": (extra or "").upper(),
                }
            )

    failures: list[str] = []
    copied_total = 0
    source_tables = [
        row[0]
        for row in source.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
    ]

    for table in source_tables:
        if table in SKIP_TABLES:
            continue
        if table not in target_columns:
            failures.append(f"{table}: target table missing")
            continue

        source_columns = [
            row[1] for row in source.execute(f'PRAGMA table_info("{table}")')
        ]
        target_info = target_columns[table]
        target_names = {item["name"] for item in target_info}
        missing = [name for name in source_columns if name not in target_names]
        if missing:
            failures.append(f"{table}: target lacks columns {missing}")
            continue
        required_missing = [
            item["name"]
            for item in target_info
            if item["name"] not in source_columns
            and not item["nullable"]
            and item["default"] is None
            and "AUTO_INCREMENT" not in item["extra"]
            and "GENERATED" not in item["extra"]
        ]
        if required_missing:
            failures.append(f"{table}: source lacks required columns {required_missing}")
            continue

        source_count = source.execute(
            f'SELECT COUNT(*) FROM "{table}"'
        ).fetchone()[0]
        with target.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {quote(table)}")
            target_count = cursor.fetchone()[0]
            if target_count and not args.truncate:
                failures.append(
                    f"{table}: target already has {target_count} rows "
                    "(use --truncate to replace)"
                )
                continue
            if target_count:
                cursor.execute(f"TRUNCATE TABLE {quote(table)}")

        columns = ",".join(quote(name) for name in source_columns)
        placeholders = ",".join(["%s"] * len(source_columns))
        insert_sql = (
            f"INSERT INTO {quote(table)} ({columns}) VALUES ({placeholders})"
        )
        select_sql = (
            "SELECT "
            + ",".join('"' + name.replace('"', '""') + '"' for name in source_columns)
            + f' FROM "{table}"'
        )
        json_indexes = [
            index
            for index, name in enumerate(source_columns)
            if next(
                item["type"] for item in target_info if item["name"] == name
            )
            == "json"
        ]

        def normalize(row: tuple) -> tuple:
            # MySQL JSON columns only accept JSON text here; SQLite stores raw
            # Python numbers (e.g. 0) that JSON.parse would accept via a string.
            if not json_indexes:
                return row
            values = list(row)
            for index in json_indexes:
                value = values[index]
                if value is None or isinstance(value, (str, bytes, bytearray)):
                    continue
                values[index] = json.dumps(value)
            return tuple(values)

        inserted = 0
        try:
            rows = source.execute(select_sql)
            with target.cursor() as cursor:
                while True:
                    batch = rows.fetchmany(args.batch_size)
                    if not batch:
                        break
                    cursor.executemany(
                        insert_sql, [normalize(row) for row in batch]
                    )
                    inserted += len(batch)
                cursor.execute(f"SELECT COUNT(*) FROM {quote(table)}")
                final_count = cursor.fetchone()[0]
            if final_count != source_count:
                raise RuntimeError(
                    f"row count mismatch: sqlite={source_count} mysql={final_count}"
                )
            target.commit()
        except Exception as exc:  # noqa: BLE001 - report and roll back this table
            target.rollback()
            failures.append(f"{table}: {type(exc).__name__}: {exc}")
            print(f"FAIL {table}: {exc}", flush=True)
            continue

        copied_total += inserted
        print(f"OK   {table}: {inserted} rows", flush=True)

    with target.cursor() as cursor:
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
    target.commit()
    target.close()
    source.close()

    if failures:
        print(f"\n{len(failures)} table(s) failed:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print(f"\nall tables copied, {copied_total} rows", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
