# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read the catalog back, in the vocabulary of the catalog.

Ingestion tests assert on what the catalog *contains*, and this answers that in
terms of databases, schemas, tables and columns rather than rows and joins — so
a test reads as a statement about the catalog rather than about the schema that
happens to hold it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, select

from auto_ontology.dal import schema as s
from auto_ontology.dal.session import store


def wipe(database_name: str) -> None:
    """Remove a database and everything under it, by cascade."""
    store().query_write(
        s.catalog_database.delete().where(s.catalog_database.c.name == database_name)
    )


def _tables_of(database_name: str) -> Select:
    return (
        select(s.catalog_table.c.id, s.catalog_table.c.name)
        .join(s.catalog_schema, s.catalog_schema.c.id == s.catalog_table.c.schema_id)
        .join(
            s.catalog_database,
            s.catalog_database.c.id == s.catalog_schema.c.database_id,
        )
        .where(s.catalog_database.c.name == database_name)
    )


def tables(database_name: str) -> set[str]:
    return {r["name"] for r in store().query_read(_tables_of(database_name))}


def _columns_of(database_name: str, table: str | None = None) -> Select:
    owners = _tables_of(database_name)
    if table is not None:
        owners = owners.where(s.catalog_table.c.name == table)
    return select(s.catalog_column).where(
        s.catalog_column.c.table_id.in_(select(owners.subquery().c.id))
    )


def columns(database_name: str, table: str) -> set[str]:
    return {r["name"] for r in store().query_read(_columns_of(database_name, table))}


def column_property(database_name: str, table: str, column: str, prop: str) -> Any:
    """One column property. *prop* is a column of ``catalog_column``."""
    rows = store().query_read(
        _columns_of(database_name, table).where(s.catalog_column.c.name == column)
    )
    return rows[0][prop] if rows else None


def entity_counts(database_name: str) -> dict[str, int]:
    """How many of each catalog entity a database holds.

    A duplicate-creating bug preserves every *name*, so counts are what a no-op
    re-ingest has to be checked against.
    """

    def count(statement: Select) -> int:
        return store().query_read(
            select(func.count().label("n")).select_from(statement.subquery())
        )[0]["n"]

    schemas = (
        select(s.catalog_schema.c.id)
        .join(
            s.catalog_database,
            s.catalog_database.c.id == s.catalog_schema.c.database_id,
        )
        .where(s.catalog_database.c.name == database_name)
    )
    return {
        "Schema": count(schemas),
        "Table": count(_tables_of(database_name)),
        "Column": count(_columns_of(database_name)),
    }


def foreign_keys(database_name: str) -> set[tuple[str, str]]:
    """``(source column name, target column name)`` for each foreign key."""
    source = s.catalog_column.alias("source_column")
    target = s.catalog_column.alias("target_column")
    rows = store().query_read(
        select(source.c.name.label("src"), target.c.name.label("dst"))
        .select_from(
            s.column__foreign_key.join(
                source, source.c.id == s.column__foreign_key.c.source_column_id
            ).join(target, target.c.id == s.column__foreign_key.c.target_column_id)
        )
        .where(source.c.table_id.in_(select(_tables_of(database_name).subquery().c.id)))
    )
    return {(r["src"], r["dst"]) for r in rows}
