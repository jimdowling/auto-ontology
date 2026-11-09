# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Run the SQL a chat turn issues: one read-only query, logged, and capped in time.

These behaviours deliberately live here rather than in the connectors. A
connector's ``execute`` is the chokepoint for *all* SQL — ingestion
introspection and column profiling included — where neither behaviour is
wanted: logging there buries a question's few statements under hundreds of
housekeeping queries, and a short timeout would break metadata scans over a
large ``information_schema``, which legitimately take minutes.

Only agent-issued SQL reaches the calls here.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from auto_ontology.infra.feature_flags import get_sql_query_timeout_seconds

logger = logging.getLogger(__name__)

# Generated SQL is normally short, but a pathological statement shouldn't flood
# the log; keep enough to be recognisable and say how much was cut.
_MAX_LOGGED_SQL_CHARS = 4000


# Nodes that write or change state wherever they sit in the tree: a CTE may
# hold a DELETE ... RETURNING on Postgres, and SELECT ... INTO creates a table.
_WRITES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Into,
    exp.Command,
)


class ReadOnlySQLError(ValueError):
    """The SQL is not exactly one query that only reads."""


def require_read_only(sql: str, dialect: str | None) -> None:
    """Raise :class:`ReadOnlySQLError` unless ``sql`` is a single SELECT or WITH
    query with no write anywhere in it. SQL sqlglot cannot parse is refused."""
    try:
        statements = [
            statement
            for statement in sqlglot.parse(sql, read=dialect or None)
            if statement is not None
        ]
    except SqlglotError as exc:
        raise ReadOnlySQLError(f"Only a single SELECT query may run: {exc}") from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise ReadOnlySQLError("Only a single SELECT query may run")
    if statements[0].find(*_WRITES) is not None:
        raise ReadOnlySQLError("Only a query that reads may run; this one writes")


def truncate_sql(sql: str) -> str:
    """Return *sql* capped at a length that is safe to log."""
    if len(sql) <= _MAX_LOGGED_SQL_CHARS:
        return sql
    omitted = len(sql) - _MAX_LOGGED_SQL_CHARS
    return f"{sql[:_MAX_LOGGED_SQL_CHARS]}… [{omitted} more chars]"


def log_chat_sql(connector: Any, sql: str, *, kind: str = "chat SQL") -> None:
    """Log one agent-issued statement at INFO."""
    database = getattr(connector, "database_name", None) or "unknown"
    logger.info("[%s] Executing %s:\n%s", database, kind, truncate_sql(sql))


def execute_chat_sql(
    connector: Any,
    sql: str,
    *,
    kind: str = "chat SQL",
    timeout_s: float | None = None,
) -> pd.DataFrame:
    """Log and run one agent-issued statement, capped in time.

    A user is waiting on the answer and the pipeline allows one stream at a
    time, so a runaway query would pin the slot. The cap is *timeout_s*, or
    when that is ``None`` the SQL Query Timeout from Settings > Agent Settings
    (30s unless an admin changed it, and always 30s without the frontend).
    Connecting and warehouse scheduling may sit outside it, so expect roughly
    the cap plus a couple of seconds of wall clock.

    Every built-in connector honours the cap -- server side where the engine
    has a statement timeout, client side for DuckDB, SQLite and HeavyDB. One
    that doesn't advertise ``supports_statement_timeout`` is called unchanged,
    so the cap never breaks a connector with no way to honour it.

    Raises :class:`ReadOnlySQLError`, before anything runs, for SQL that is not
    one read-only query.
    """
    require_read_only(sql, getattr(connector, "dialect", None))
    log_chat_sql(connector, sql, kind=kind)

    if not getattr(connector, "supports_statement_timeout", False):
        return connector.execute(sql)
    if timeout_s is None:
        timeout_s = get_sql_query_timeout_seconds()
    return connector.execute(sql, timeout_s=timeout_s)
