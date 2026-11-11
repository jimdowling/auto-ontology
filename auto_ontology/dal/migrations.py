# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Creates and upgrades the store's tables, step by recorded step.

On Hopsworks the ontology app's database user cannot run DDL: the platform's
app-tables API creates and alters the app's tables on its behalf, adding the
engine, tablespace and ``STORAGE DISK`` itself (:class:`AppTablesDDL`). Tests
and local runs execute the same DDL directly (:class:`DirectDDL`).

The steps are one ``create`` per table in :data:`~auto_ontology.dal.schema.METADATA`,
in foreign-key order, with the table's indexes inline, followed by
:data:`ALTERATIONS` in the order they were written. Every step is recorded in
``schema_version`` when it lands, so a run interrupted half way resumes where
it stopped. Creating a table is idempotent on both backends, which covers a
table created in one RonDB region whose record never landed. An alteration is
never edited once released; a schema change is a new one appended to the list.

The ontology app runs :func:`migrate` at startup. It is the only writer: a
Hopsworks app has one replica, and jobs only check :func:`schema_state`.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import Index, Table, select, text
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from auto_ontology.dal import schema as s
from auto_ontology.dal.session import get_engine

logger = logging.getLogger(__name__)

_DIALECT = mysql.dialect()

#: Every string column states its character set: the project's online database
#: on Hopsworks does not default to utf8mb4, and names and descriptions come
#: from source databases in any language.
_STRING_TYPE = re.compile(r"\b(VARCHAR\(\d+\)|MEDIUMTEXT|TEXT)(?! CHARACTER SET)")


@dataclass(frozen=True)
class Step:
    """One recorded unit of DDL. ``sql`` is a column list for a create, or what
    follows ``ALTER TABLE <name>`` for an alteration."""

    id: str
    table: str
    kind: str
    sql: str


#: Schema changes after the first release, appended in order and never edited.
ALTERATIONS: list[Step] = []


class DDL(Protocol):
    def create_table(self, name: str, definition: str) -> None: ...

    def alter_table(self, name: str, alteration: str) -> None: ...


class DirectDDL:
    """Runs the DDL on the DAL's own connection, which needs DDL rights."""

    def create_table(self, name: str, definition: str) -> None:
        with get_engine().begin() as connection:
            connection.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS `{name}` ({definition}) "
                    "ENGINE=ndbcluster DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"
                )
            )

    def alter_table(self, name: str, alteration: str) -> None:
        with get_engine().begin() as connection:
            connection.execute(text(f"ALTER TABLE `{name}` {alteration}"))


class AppTablesDDL:
    """Runs the DDL through a Hopsworks app's tables API (``hopsworks_common.app.App``)."""

    def __init__(self, app: Any) -> None:
        self._app = app

    def create_table(self, name: str, definition: str) -> None:
        self._app.create_table(name, definition)

    def alter_table(self, name: str, alteration: str) -> None:
        self._app.alter_table(name, alteration)


def _index_clause(index: Index) -> str:
    columns = ", ".join(f"`{column.name}`" for column in index.columns)
    kind = "UNIQUE INDEX" if index.unique else "INDEX"
    return f"{kind} `{index.name}` ({columns})"


def table_definition(table: Table) -> str:
    """The text inside ``CREATE TABLE <name> ( ... )`` for ``table``, indexes included."""
    ddl = str(CreateTable(table).compile(dialect=_DIALECT)).strip()
    body = ddl[ddl.index("(") + 1 : ddl.rindex(")")]
    clauses = [line.strip().rstrip(",") for line in body.splitlines() if line.strip()]
    clauses.extend(
        _index_clause(index) for index in sorted(table.indexes, key=lambda i: i.name)
    )
    return ", ".join(
        _STRING_TYPE.sub(r"\1 CHARACTER SET utf8mb4 COLLATE utf8mb4_bin", clause)
        for clause in clauses
    )


def steps() -> list[Step]:
    """Every step, ``schema_version`` first so the others can be recorded."""
    tables = [s.schema_version] + [
        table for table in s.METADATA.sorted_tables if table is not s.schema_version
    ]
    creates = [
        Step(
            id=f"create:{table.name.removeprefix(s.TABLE_PREFIX)}",
            table=table.name,
            kind="create",
            sql=table_definition(table),
        )
        for table in tables
    ]
    return creates + ALTERATIONS


def applied_steps() -> set[str]:
    """The recorded step ids. Raises when ``schema_version`` is missing or unreadable."""
    with get_engine().connect() as connection:
        return set(connection.execute(select(s.schema_version.c.step)).scalars())


def migrate(ddl: DDL) -> list[str]:
    """Apply every unrecorded step through ``ddl``; return the ids applied.

    Stops at the first failing step and raises its error; the steps before it
    stay recorded, so the next run resumes there.
    """
    all_steps = steps()
    ddl.create_table(s.schema_version.name, all_steps[0].sql)
    done = applied_steps()
    applied: list[str] = []
    for step in all_steps:
        if step.id in done:
            continue
        logger.info("Schema step %s", step.id)
        if step.kind == "create":
            ddl.create_table(step.table, step.sql)
        else:
            ddl.alter_table(step.table, step.sql)
        with get_engine().begin() as connection:
            connection.execute(s.schema_version.insert().values(step=step.id))
        applied.append(step.id)
    return applied
