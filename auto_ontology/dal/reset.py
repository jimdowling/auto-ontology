# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Per-database reset: drop a database's catalog rows and their embeddings.

The single source of truth for wiping one database's ingested data.

**This module is where the schema pays for itself.** Containment is a parent
foreign key, so a database's whole catalog tier is the rows below its
``catalog_database`` row, and the ``ON DELETE CASCADE`` foreign keys in
:data:`auto_ontology.dal.schema.METADATA` say what lies below each row. A child
table added later is found the same way and cannot be missed here.

**Deletes go bottom-up, at most ``_BATCH`` rows per transaction.** RonDB changes
at most 32768 rows in one transaction, cascaded deletes included, so one
cascading delete of a large catalog fails. Each batch of rows has its children
deleted first, so its own delete cascades to nothing. A reset is therefore many
transactions: one interrupted part-way leaves a smaller catalog, and running it
again finishes the job. Inside a caller's :func:`write_transaction` the batches
join that one transaction and the limit is the caller's to respect.

Two consequences worth knowing:

* **Deletes never cross a database.** Foreign keys point downward within one
  database, so resetting one cannot reach another's data — including through a
  Term the two share, which survives.
* **A scoped semantic reset does not reach ``PqlAnalysis``.** Nothing connects
  one to a database, so there is no scope to match it by. A scoped reset
  silently deleting every predictive analysis in the deployment would be a
  worse surprise than the gap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import (
    Column,
    ColumnElement,
    Select,
    Table,
    and_,
    or_,
    select,
    true,
    tuple_,
    union,
)

from auto_ontology.dal import schema as s
from auto_ontology.dal.ops import chunks, delete_returning
from auto_ontology.dal.session import IN_QUERY_BATCH, store
from auto_ontology.vdb import get_data_vdb, get_semantic_vdb

logger = logging.getLogger(__name__)

#: Rows one transaction deletes. Their children are gone by then, so this is
#: the whole of the transaction's changed rows.
_BATCH = IN_QUERY_BATCH


@dataclass
class ResetResult:
    """Summary of what a :func:`delete_all_data` call removed."""

    #: ``None`` when the reset covered every database, matching
    #: ``delete_all_data``'s own optional argument.
    database_name: str | None
    data_rows: int
    semantic_rows: int


def _cascade_children(table: Table) -> list[tuple[Table, list[Column]]]:
    """Tables with an ``ON DELETE CASCADE`` foreign key to *table*, with its columns."""
    children = []
    for child in s.METADATA.sorted_tables:
        columns = [
            fk.parent
            for fk in child.foreign_keys
            if fk.column.table is table and (fk.ondelete or "").upper() == "CASCADE"
        ]
        if columns:
            children.append((child, columns))
    return children


def _delete_tree(table: Table, where: ColumnElement[bool]) -> int:
    """Delete the rows *where* selects and everything that cascades from them.

    Children first, at most ``_BATCH`` rows per transaction. *where* must not
    read the children, which are gone before their parents. Returns the number
    of *table* rows deleted.
    """
    key = list(table.primary_key.columns)
    children = _cascade_children(table)
    deleted = 0
    while True:
        batch = store().query_read(select(*key).where(where).limit(_BATCH))
        if not batch:
            return deleted
        if children:
            ids = [row["id"] for row in batch]
            for child, columns in children:
                _delete_tree(child, or_(*(column.in_(ids) for column in columns)))
        if len(key) == 1:
            match = key[0].in_([row[key[0].name] for row in batch])
        else:
            match = tuple_(*key).in_(
                [tuple(row[column.name] for column in key) for row in batch]
            )
        # *where* again under the lock: a statement an ingest linked since the
        # read is no longer an orphan.
        deleted += len(delete_returning(table, and_(match, where), key))


def _delete_ids(table: Table, ids: list[str]) -> int:
    return sum(
        _delete_tree(table, table.c.id.in_(batch)) for batch in chunks(ids, _BATCH)
    )


def _ids(statement: Select) -> list[str]:
    return [row["id"] for row in store().query_read(statement)]


def _table_ids(database_name: str) -> Select:
    """The tables of one database, as a subquery."""
    return (
        select(s.catalog_table.c.id)
        .select_from(
            s.catalog_table.join(
                s.catalog_schema, s.catalog_schema.c.id == s.catalog_table.c.schema_id
            ).join(
                s.catalog_database,
                s.catalog_database.c.id == s.catalog_schema.c.database_id,
            )
        )
        .where(s.catalog_database.c.name == database_name)
    )


def _delete_scoped_semantic(database_name: str) -> int:
    """Delete the semantic rows belonging to one database.

    "Belonging" is resolved per entity, because each reaches a database by a
    different path:

    * a **Term** through the tables that represent it;
    * a **ColumnAttribute** through its ``table_id``;
    * a **SqlAttribute** and a **CustomAnalysis** through the tables their SQL
      references.

    Each is deleted only when **every** table it touches belongs to this
    database — the same all-or-nothing shape the zone reads use, and for the
    same reason inverted: a Term shared with another database is that other
    database's data too, and a reset of this one must not take it.

    ``PqlAnalysis``, ``TextAttribute`` and ``Analysis`` are absent here on
    purpose: nothing connects them to a database, so there is no scope that
    would select them.

    Every id is read before anything is deleted: deleting a Term deletes the
    ``table__term`` rows that scoped it.
    """
    tables = _table_ids(database_name)

    def only_ours(owner_column: ColumnElement, table_column: ColumnElement) -> Select:
        """Owners whose links all land inside this database, and at least one does."""
        # Not correlated: the subquery reads the same link table as the query
        # around it, and asks about every row of it, not the current one.
        outside = (
            select(owner_column).where(table_column.notin_(tables)).correlate(None)
        )
        return (
            select(owner_column.label("id"))
            .where(table_column.in_(tables), owner_column.notin_(outside))
            .distinct()
        )

    doomed: list[tuple[Table, list[str]]] = [
        (s.term, _ids(only_ours(s.table__term.c.term_id, s.table__term.c.table_id))),
        (
            s.column_attribute,
            _ids(
                select(s.column_attribute.c.id).where(
                    s.column_attribute.c.table_id.in_(tables)
                )
            ),
        ),
    ]
    for owner_table, link_table, owner_column in (
        (s.sql_attribute, s.sql_attribute__sql, s.sql_attribute__sql.c.attribute_id),
        (
            s.custom_analysis,
            s.custom_analysis__sql,
            s.custom_analysis__sql.c.analysis_id,
        ),
    ):
        touched = (
            select(owner_column, s.sql_query__table.c.table_id)
            .select_from(
                link_table.join(
                    s.sql_query__table,
                    s.sql_query__table.c.sql_query_id == link_table.c.sql_query_id,
                )
            )
            .subquery("touched")
        )
        doomed.append(
            (
                owner_table,
                _ids(only_ours(touched.c[owner_column.name], touched.c.table_id)),
            )
        )
    return sum(_delete_ids(table, ids) for table, ids in doomed)


def _delete_all_semantic() -> int:
    """Delete every semantic row, in every database.

    Unscoped, so ``PqlAnalysis``, ``TextAttribute`` and ``Analysis`` *are*
    included — nothing has to connect them to a database for this to reach
    them.
    """
    return sum(
        _delete_tree(table, true())
        for table in (
            s.term,
            s.column_attribute,
            s.sql_attribute,
            s.text_attribute,
            s.analysis,
            s.pql_analysis,
            s.custom_analysis,
        )
    )


def delete_semantic_layer(database_name: str | None = None) -> int:
    """Delete semantic rows and their embeddings. Catalog rows survive.

    Custom analyses, SQL and predictive alike, are part of what goes: they are
    user-authored, so nothing recompiles them afterwards.

    Returns the number of **vector rows** deleted, not database rows — the
    caller reports it as "embeddings removed". The row count is logged.
    """
    _delete_semantic_rows(database_name)
    return _delete_semantic_vectors(database_name)


def _delete_semantic_rows(database_name: str | None) -> int:
    """Semantic rows only, no embeddings."""
    if database_name is None:
        deleted = _delete_all_semantic()
    else:
        deleted = _delete_scoped_semantic(database_name)
    logger.info(
        "delete_semantic_layer: removed %d semantic rows for database %s",
        deleted,
        database_name or "<all>",
    )
    return deleted


def _delete_semantic_vectors(database_name: str | None) -> int:
    """The embeddings, after the rows.

    The vector store sits outside the DAL's transactions. A vector whose row is
    gone is dead weight the next embed pass overwrites, whereas a row whose
    vector is gone is a hit retrieval can no longer explain, so the rows go
    first.
    """
    semantic_vdb = get_semantic_vdb()
    if database_name is None:
        semantic_deleted = semantic_vdb.delete_all()
    else:
        semantic_deleted = len(semantic_vdb.delete_by_database(database_name))

    logger.info(
        "delete_semantic_layer: removed %d semantic vector rows for database %s",
        semantic_deleted,
        database_name or "<all>",
    )
    return semantic_deleted


def _delete_orphaned_statements(candidate_ids: list[str] | None = None) -> int:
    """Delete ``sql_query`` rows nothing references any more.

    "Orphan" is defined as having no link left in *any* of the four tables that
    point at a statement, not just the two the catalog deletes emptied. A
    statement can also be owned by a SqlAttribute or a CustomAnalysis, and those
    survive a data-layer reset — deleting on the catalog links alone would take
    the semantic tier's statements with it.

    *candidate_ids* narrows the sweep to statements the caller just unlinked.
    Without it this is a **global** delete of every unreferenced statement, and
    a statement is unreferenced for a moment during any ingest: ``add_query``
    inserts the ``sql_query`` row before its links, so a scoped reset running
    concurrently with an ingest of a *different* database would delete that
    in-flight row and the ingest would fail on a vanished foreign key. Scoped,
    the sweep can only touch rows the reset itself orphaned.

    ``None`` keeps the global behaviour, which is what a whole-store reset
    wants — there is no other database left to race with.
    """
    referenced = union(
        select(s.sql_query__table.c.sql_query_id),
        select(s.sql_query__column.c.sql_query_id),
        select(s.sql_attribute__sql.c.sql_query_id),
        select(s.custom_analysis__sql.c.sql_query_id),
    )
    orphaned = s.sql_query.c.id.not_in(referenced)
    if candidate_ids is None:
        removed = _delete_tree(s.sql_query, orphaned)
    else:
        removed = sum(
            _delete_tree(s.sql_query, orphaned & s.sql_query.c.id.in_(batch))
            for batch in chunks(candidate_ids, _BATCH)
        )
    if removed:
        logger.info("delete_data_layer: removed %d orphaned statement rows", removed)
    return removed


def delete_data_layer(database_name: str | None = None) -> int:
    """Delete a database's catalog rows and its embeddings.

    Returns the number of vector rows deleted. The embeddings follow the rows,
    for the reason given on :func:`_delete_semantic_vectors`.
    """
    _delete_data_rows(database_name)
    return _delete_data_vectors(database_name)


def _delete_data_rows(database_name: str | None = None) -> int:
    """Catalog rows and the statements they orphaned.

    Schemas, tables, columns, foreign keys, joins, statement links, tags and
    zone targets all go as the database's cascade children.

    Statements are the exception and need the second delete below: ``sql_query``
    has no foreign key into the catalog, so the cascade takes its *links* and
    leaves the rows. Left behind they are invisible but not harmless — dedup
    matches on ``sql_hash``, so the next ingest merges into the old row and
    ``total_counter`` accumulates across resets.

    Returns the number of ``catalog_database`` rows deleted.
    """
    # The statements this database's tables reference, captured *before* the
    # catalog deletes remove those links — afterwards there is no way back.
    candidates: list[str] | None = None
    if database_name is not None:
        candidates = [
            row["sql_query_id"]
            for row in store().query_read(
                select(s.sql_query__table.c.sql_query_id)
                .where(s.sql_query__table.c.table_id.in_(_table_ids(database_name)))
                .distinct()
            )
        ]

    where = (
        true() if database_name is None else s.catalog_database.c.name == database_name
    )
    deleted = _delete_tree(s.catalog_database, where)
    logger.info(
        "delete_data_layer: removed %d database rows for database %s",
        deleted,
        database_name or "<all>",
    )
    _delete_orphaned_statements(candidates)
    return deleted


def _delete_data_vectors(database_name: str | None) -> int:
    """The embeddings, after the rows — see :func:`_delete_semantic_vectors`."""
    data_vdb = get_data_vdb()
    if database_name is None:
        data_deleted = data_vdb.delete_all()
    else:
        data_deleted = len(data_vdb.delete_by_database(database_name))

    logger.info(
        "delete_data_layer: removed %d data vector rows for database %s",
        data_deleted,
        database_name or "<all>",
    )
    return data_deleted


def delete_all_data(database_name: str | None = None) -> ResetResult:
    """Delete every trace of a database, both layers included.

    **Order matters**: the semantic rows are identified *through* the catalog —
    a Term by the tables that represent it, a SqlAttribute by the tables its
    SQL hits. Delete the catalog first and those links are already gone, so the
    semantic pass would find nothing to scope and leave every Term behind. The
    same order makes a re-run after an interruption finish the job: the
    semantic rows are all gone before the first catalog row goes.

    The semantic layer is user-authored, so nothing recompiles it; a reset that
    stopped after the semantic pass has still lost it.
    """
    _delete_semantic_rows(database_name)
    _delete_data_rows(database_name)

    semantic_rows = _delete_semantic_vectors(database_name)
    data_rows = _delete_data_vectors(database_name)

    result = ResetResult(
        database_name=database_name,
        data_rows=data_rows,
        semantic_rows=semantic_rows,
    )
    logger.info(
        "delete_all_data: removed %d vector rows for database %s "
        "(%d data, %d semantic)",
        result.data_rows + result.semantic_rows,
        database_name,
        result.data_rows,
        result.semantic_rows,
    )
    return result
