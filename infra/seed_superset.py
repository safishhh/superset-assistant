"""Seed the isolated Superset instance with a demo dataset, users, and RLS.

Run inside the Superset container after `superset db upgrade` and
`superset init`:

    python /app/pythonpath/seed_superset.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import date, timedelta

from sqlalchemy import (
    Column,
    Date,
    Double,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    inspect,
    text,
)

from superset.app import create_app

# App initialization must happen before importing models that touch encrypted
# fields; otherwise Superset raises "App not initialized yet".
app = create_app()

from superset import db, security_manager as sm  # noqa: E402
from superset.connectors.sqla.models import (  # noqa: E402
    RowLevelSecurityFilter,
    SqlaTable,
    SqlMetric,
)
from superset.models.core import Database  # noqa: E402
from superset.subjects.utils import get_or_create_role_subject  # noqa: E402

DATABASE_NAME = "assistant_demo"
TABLE_NAME = "sales"
SCHEMA_NAME = os.environ.get("DEMO_SCHEMA") or None

METRICS = [
    ("count", "COUNT(*)", "COUNT", "订单数"),
    ("total_amount", "SUM(amount)", "SUM", "销售额"),
    ("total_quantity", "SUM(quantity)", "SUM", "销量"),
    ("avg_amount", "AVG(amount)", "AVG", "平均单价"),
]

COLUMN_LABELS = {
    "id": "ID",
    "order_date": "日期",
    "region": "区域",
    "category": "品类",
    "channel": "渠道",
    "amount": "金额",
    "quantity": "数量",
}

USERS = [
    ("east", "East", "User", "east@example.com", "region = 'east'"),
    ("west", "West", "User", "west@example.com", "region = 'west'"),
]


def log(message: str) -> None:
    print(f"[seed] {message}", flush=True)


def sqlite_path(uri: str) -> str | None:
    if not uri.startswith("sqlite:"):
        return None
    return uri.split("sqlite:///")[-1].split("?")[0]


def enable_wal(uri: str) -> None:
    path = sqlite_path(uri)
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.commit()
    connection.close()


def ensure_demo_data() -> None:
    uri = os.environ["DEMO_DB_URI"]
    if uri.startswith("sqlite:"):
        enable_wal(uri)
    engine = create_engine(uri)
    metadata = MetaData()
    sales = Table(
        TABLE_NAME,
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("order_date", Date, nullable=False),
        Column("region", String(32), nullable=False),
        Column("category", String(32), nullable=False),
        Column("channel", String(32), nullable=False),
        Column("amount", Double, nullable=False),
        Column("quantity", Integer, nullable=False),
        Index("idx_sales_date", "order_date"),
        Index("idx_sales_region", "region"),
        Index("idx_sales_category", "category"),
    )
    inspector = inspect(engine)
    if inspector.has_table(TABLE_NAME):
        with engine.connect() as connection:
            count = connection.execute(
                text(f"SELECT COUNT(*) FROM {TABLE_NAME}")
            ).scalar()
        if count:
            log(f"演示数据已存在：sales {count} 行")
            return
    else:
        metadata.create_all(engine)

    rows: list[dict] = []
    current = date(2024, 1, 1)
    end = date(2026, 10, 24)
    while current <= end:
        for region in ("east", "west"):
            for category in ("A", "B", "C"):
                for channel in ("online", "offline"):
                    amount = round(
                        100
                        + 20 * current.month
                        + 10 * current.day
                        + (30 if region == "east" else 0)
                        + {"A": 50, "B": 20, "C": 0}[category]
                        + (15 if channel == "online" else 0)
                        + (25 if current.weekday() in (5, 6) else 0)
                        + (-60 if current >= date(2026, 8, 15) and region == "east" else 0)
                        + (40 if current >= date(2026, 1, 1) and category == "C" else 0)
                        - (20 if current >= date(2026, 1, 1) and category == "A" else 0)
                        + (current.timetuple().tm_yday % 7) * 2,
                        2,
                    )
                    rows.append(
                        {
                            "order_date": current,
                            "region": region,
                            "category": category,
                            "channel": channel,
                            "amount": amount,
                            "quantity": max(1, round(amount / 100)),
                        }
                    )
        current += timedelta(days=1)
    with engine.begin() as connection:
        connection.execute(sales.insert(), rows)
    log(f"创建演示数据：sales {len(rows)} 行（2024-01-01 .. 2026-10-24）")


def ensure_database() -> Database:
    uri = os.environ["DEMO_DB_URI"]
    database = (
        db.session.query(Database)
        .filter_by(database_name=DATABASE_NAME)
        .one_or_none()
    )
    if database is None:
        database = Database(
            database_name=DATABASE_NAME,
            sqlalchemy_uri=uri,
            expose_in_sqllab=True,
            allow_dml=False,
            allow_ctas=False,
            allow_cvas=False,
            allow_run_async=False,
        )
        db.session.add(database)
        db.session.commit()
        log(f"created database {DATABASE_NAME}")
    elif database.sqlalchemy_uri != uri:
        database.sqlalchemy_uri = uri
        db.session.merge(database)
        db.session.commit()
        log(f"updated database {DATABASE_NAME} -> {uri.split('@')[-1]}")
    else:
        log(f"database {DATABASE_NAME} already exists")
    return database


def ensure_dataset(database: Database) -> SqlaTable:
    dataset = (
        db.session.query(SqlaTable)
        .filter_by(
            table_name=TABLE_NAME,
            database_id=database.id,
            schema=SCHEMA_NAME,
        )
        .one_or_none()
    )
    if dataset is None:
        dataset = SqlaTable(
            table_name=TABLE_NAME,
            schema=SCHEMA_NAME,
            database=database,
        )
        db.session.add(dataset)
        db.session.commit()
        log(f"created dataset {TABLE_NAME}")

    results = dataset.fetch_metadata()
    dataset.main_dttm_col = "order_date"
    db.session.merge(dataset)
    db.session.commit()
    log(
        "synced columns: "
        f"added={len(results.added)} modified={len(results.modified)} "
        f"removed={len(results.removed)}"
    )

    for column in dataset.columns:
        label = COLUMN_LABELS.get(column.column_name)
        if label and column.verbose_name != label:
            column.verbose_name = label

    existing = {metric.metric_name: metric for metric in dataset.metrics}
    for name, expression, metric_type, verbose_name in METRICS:
        metric = existing.get(name)
        if metric is None:
            dataset.metrics.append(
                SqlMetric(
                    metric_name=name,
                    expression=expression,
                    metric_type=metric_type,
                    verbose_name=verbose_name,
                )
            )
        elif metric.verbose_name != verbose_name:
            metric.verbose_name = verbose_name
    db.session.merge(dataset)
    db.session.commit()
    log(f"metrics: {', '.join(sorted(m.metric_name for m in dataset.metrics))}")
    log(f"dataset perm: {dataset.perm}")
    return dataset


def ensure_role(name: str):
    role = sm.find_role(name)
    if role is None:
        role = sm.add_role(name)
        log(f"created role {name}")
    return role


def grant(role, permission: str, view_menu: str) -> None:
    pv = sm.add_permission_view_menu(permission, view_menu)
    sm.add_permission_role(role, pv)


def ensure_user(username: str, first: str, last: str, email: str, role, password: str):
    user = sm.find_user(username=username)
    if user is None:
        user = sm.add_user(
            username=username,
            first_name=first,
            last_name=last,
            email=email,
            role=role,
            password=password,
        )
        log(f"created user {username}")
    elif role not in user.roles:
        user.roles.append(role)
        db.session.merge(user)
        db.session.commit()
        log(f"granted role {role.name} to {username}")
    return user


def ensure_rls(name: str, clause: str, dataset: SqlaTable, role) -> None:
    rls = (
        db.session.query(RowLevelSecurityFilter)
        .filter_by(name=name)
        .one_or_none()
    )
    if rls is not None:
        log(f"RLS {name} already exists")
        return
    rls = RowLevelSecurityFilter(
        name=name,
        filter_type="Regular",
        clause=clause,
        group_key="region",
    )
    rls.tables.append(dataset)
    subject = get_or_create_role_subject(role.id)
    if subject is None:
        raise RuntimeError(f"could not create subject for role {role.name}")
    rls.subjects.append(subject)
    db.session.add(rls)
    db.session.commit()
    log(f"created RLS {name}: {clause}")


def ensure_admin() -> None:
    admin_role = sm.find_role("Admin")
    if admin_role is None:
        raise RuntimeError("Admin role missing; run `superset init` first")
    # AI 助手是否可用改由 AI 管理后台按用户控制；不再使用 can_use 权限。
    for permission in ("can_admin_ticket", "can_admin_redirect"):
        grant(admin_role, permission, "assistant")
    username = os.environ.get("SUPERSET_ADMIN_USERNAME", "admin")
    password = os.environ.get("SUPERSET_ADMIN_PASSWORD", "admin")
    email = os.environ.get("SUPERSET_ADMIN_EMAIL", "admin@example.com")
    if sm.find_user(username=username) is None:
        sm.add_user(
            username=username,
            first_name="Admin",
            last_name="User",
            email=email,
            role=admin_role,
            password=password,
        )
        log(f"created admin user {username}")


def main() -> int:
    enable_wal(os.environ["SUPERSET_METADATA_URI"])
    ensure_demo_data()
    with app.app_context():
        database = ensure_database()
        dataset = ensure_dataset(database)

        for username, first, last, email, clause in USERS:
            role = ensure_role(f"sales_{username}")
            grant(role, "datasource_access", dataset.perm)
            grant(role, "can_read", "Dataset")
            grant(role, "can_get_drill_info", "Dataset")
            grant(role, "can_read", "Database")
            # The chat widget is delivered as a Superset extension; users who
            # should see it need read access to the extension APIs/assets.
            for permission in ("can_info", "can_get_list", "can_content", "can_get"):
                grant(role, permission, "ExtensionsRestApi")
            grant(role, "can_read", "Extensions")
            grant(role, "can_recent_activity", "Log")
            for view_menu in ("Chart", "Dashboard", "Log"):
                grant(role, "can_read", view_menu)
            ensure_user(username, first, last, email, role, username)
            ensure_rls(f"rls_sales_{username}", clause, dataset, role)

        ensure_admin()
        log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
