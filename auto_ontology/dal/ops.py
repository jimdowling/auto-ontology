# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The write idioms the DAL used on Postgres, rebuilt for MySQL.

MySQL has no ``RETURNING`` and no ``ON CONFLICT (target)``. The helpers here
keep the call sites' shape -- write, get the rows back -- by generating ids
client-side, upserting with ``INSERT ... ON DUPLICATE KEY UPDATE``, and reading
the rows back by key in the same transaction.

``ON DUPLICATE KEY UPDATE`` fires on a conflict with *any* unique key of the
table, not a chosen one. That is the same thing on every table whose only
unique keys are its id and the conflict target; :func:`upsert` checks that,
because on a table with more unique keys an upsert can update a row the caller
never named.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from sqlalchemy import (
    ColumnElement,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    and_,
    or_,
    select,
)
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import DBAPIError

from auto_ontology.dal import session
from auto_ontology.dal.session import store, write_transaction
from auto_ontology.dal.types import new_id

Row = dict[str, Any]

DUPLICATE_KEY = 1062
ROW_IS_REFERENCED = 1451
NO_REFERENCED_ROW = 1452


def mysql_errno(exc: DBAPIError) -> int | None:
    """The MySQL error number behind a driver error, or ``None`` when it has none.

    Match on this, not on constraint names in the message: a table prefix
    renames every generated foreign key.
    """
    args = getattr(exc.orig, "args", ())
    return args[0] if args and isinstance(args[0], int) else None


def _with_id(table: Table, values: Mapping[str, Any]) -> Row:
    row = dict(values)
    if (
        "id" in table.c
        and table.c.id.primary_key
        and isinstance(table.c.id.type, String)
        and row.get("id") is None
    ):
        row["id"] = new_id()
    return row


def _primary_key(table: Table) -> list[str]:
    return [column.name for column in table.primary_key.columns]


def _match(
    table: Table, key: Sequence[str], rows: Sequence[Mapping[str, Any]]
) -> ColumnElement[bool]:
    return or_(*(and_(*(table.c[name] == row[name] for name in key)) for row in rows))


def _read_back(
    table: Table,
    key: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    returning: Sequence[Any],
) -> list[Row]:
    found: list[Row] = []
    size = session.IN_QUERY_BATCH
    for start in range(0, len(rows), size):
        batch = rows[start : start + size]
        found.extend(
            store().query_read(select(*returning).where(_match(table, key, batch)))
        )
    return found


def insert_returning(
    table: Table,
    values: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    returning: Sequence[Any],
) -> list[Row]:
    """Insert one row or many and return ``returning`` for each, in input order.

    A missing ``id`` is generated. Raises the driver's integrity error on a
    duplicate, as a plain insert would.
    """
    rows = (
        [_with_id(table, values)]
        if isinstance(values, Mapping)
        else [_with_id(table, row) for row in values]
    )
    if not rows:
        return []
    key = _primary_key(table)
    with write_transaction():
        store().query_write(table.insert().values(rows))
        found = _read_back(
            table, key, rows, [*returning, *(table.c[name] for name in key)]
        )
    by_key = {tuple(row[name] for name in key): row for row in found}
    out: list[Row] = []
    for row in rows:
        hit = by_key[tuple(row[name] for name in key)]
        out.append({column.key: hit[column.key] for column in returning})
    return out


def _check_target(table: Table, key: Sequence[str]) -> None:
    unique_keys = [
        tuple(sorted(column.name for column in constraint.columns))
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint | PrimaryKeyConstraint)
    ]
    unique_keys += [
        tuple(sorted(column.name for column in index.columns))
        for index in table.indexes
        if index.unique
    ]
    allowed = {tuple(sorted(key)), tuple(sorted(_primary_key(table)))}
    others = [unique for unique in unique_keys if unique not in allowed]
    if others:
        raise ValueError(
            f"upsert on {table.name} by {list(key)}: the table has other unique keys "
            f"{others} that ON DUPLICATE KEY UPDATE would also match"
        )


def upsert(
    table: Table,
    values: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    key: Sequence[str],
    set_: Callable[[Any], Mapping[str, Any]] | None = None,
    returning: Sequence[Any] | None = None,
) -> list[Row]:
    """``INSERT ... ON DUPLICATE KEY UPDATE`` matched on ``key``.

    ``set_`` maps MySQL's ``inserted`` row (the would-be new values, what
    Postgres called ``excluded``) to the assignments for an existing row; omit
    it to keep existing rows unchanged (``DO NOTHING``). With ``returning``,
    returns those columns of every row named in ``values``, inserted or
    existing, read back by ``key``. With ``set_``, raises ``ValueError`` when
    the table has another unique key the statement would also match; without
    it, a conflict on any unique key leaves the existing row alone, as
    Postgres's untargeted ``ON CONFLICT DO NOTHING`` does.
    """
    rows = (
        [_with_id(table, values)]
        if isinstance(values, Mapping)
        else [_with_id(table, row) for row in values]
    )
    if not rows:
        return []
    if set_ is not None:
        _check_target(table, key)
    statement = mysql_insert(table).values(rows)
    # The do-nothing form assigns the primary key to itself: the conflict key
    # may be a generated column, and MySQL refuses any assignment to one.
    pk = _primary_key(table)[0]
    assignments = (
        dict(set_(statement.inserted)) if set_ is not None else {pk: table.c[pk]}
    )
    with write_transaction():
        store().query_write(statement.on_duplicate_key_update(assignments))
        if returning is None:
            return []
        return _read_back(table, key, rows, returning)


def update_returning(
    table: Table,
    where: ColumnElement[bool],
    values: Mapping[str, Any],
    returning: Sequence[Any],
) -> list[Row]:
    """Update the rows ``where`` selects and return ``returning`` for each, after the update."""
    key = _primary_key(table)
    with write_transaction():
        hits = store().query_read(
            select(*(table.c[name] for name in key)).where(where).with_for_update()
        )
        if not hits:
            return []
        store().query_write(table.update().where(where).values(**values))
        return _read_back(table, key, hits, returning)


def delete_returning(
    table: Table,
    where: ColumnElement[bool],
    returning: Sequence[Any],
) -> list[Row]:
    """Delete the rows ``where`` selects and return ``returning`` for each, read before deleting."""
    with write_transaction():
        rows = store().query_read(select(*returning).where(where).with_for_update())
        if rows:
            store().query_write(table.delete().where(where))
        return rows


def chunks(items: Iterable[Any], size: int | None = None) -> Iterable[list[Any]]:
    """``items`` in lists of at most ``size`` (default ``IN_QUERY_BATCH``)."""
    batch: list[Any] = []
    limit = size or session.IN_QUERY_BATCH
    for item in items:
        batch.append(item)
        if len(batch) == limit:
            yield batch
            batch = []
    if batch:
        yield batch
