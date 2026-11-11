# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Reconcile the semantic vector collection with the store.

For every database, the Term and ColumnAttribute rows are rebuilt from the
store exactly as compilation embeds them; rows whose text changed since they
were last written (or that were never written, because compilation commits a
Term before embedding it and swallows an embedding failure) are embedded and
written, and vectors of Terms and attributes that no longer exist are removed.
Run after edits, and at the end of every compile.
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from typing import Any

from sqlalchemy import select

from auto_ontology.dal import schema as s
from auto_ontology.dal.session import store
from auto_ontology.dal.terms import fetch_terms_and_attributes_for_table
from auto_ontology.jobs.runtime import pipeline_lease
from auto_ontology.semantic.embed import _build_rows
from auto_ontology.utils.embedding import batch_embed_chunks, get_embed_params
from auto_ontology.vdb import get_semantic_vdb
from auto_ontology.vdb.records import to_vdb_records

logger = logging.getLogger(__name__)

#: The labels this reconciliation owns. SqlAttribute and analysis vectors are
#: written by their own services and are left alone here.
LABELS = ("Term", "ColumnAttribute")


def database_names() -> list[str]:
    return [
        row["name"]
        for row in store().query_read(
            select(s.catalog_database.c.name).order_by(s.catalog_database.c.name)
        )
    ]


def _table_ids(database_name: str) -> list[str]:
    return [
        row["id"]
        for row in store().query_read(
            select(s.catalog_table.c.id)
            .join(
                s.catalog_schema, s.catalog_schema.c.id == s.catalog_table.c.schema_id
            )
            .join(
                s.catalog_database,
                s.catalog_database.c.id == s.catalog_schema.c.database_id,
            )
            .where(s.catalog_database.c.name == database_name)
        )
    ]


def semantic_rows(database_name: str) -> list[dict[str, Any]]:
    """The Term and ColumnAttribute rows of ``database_name``, built as compilation builds them."""
    rows: dict[str, dict[str, Any]] = {}
    for table_id in _table_ids(database_name):
        terms, attrs = fetch_terms_and_attributes_for_table(table_id)
        attrs_by_term: dict[str, list[dict]] = defaultdict(list)
        for attr in attrs:
            if attr.get("term_name"):
                attrs_by_term[attr["term_name"]].append(attr)
        for term in terms:
            for row in _build_rows(
                database_name, term, attrs_by_term.get(term["name"], [])
            ):
                node_id = (row.get("metadata") or {}).get("id")
                if node_id:
                    rows[str(node_id)] = row
    return list(rows.values())


class UnembeddedRowsError(RuntimeError):
    """Rows whose text changed came back from the embedder without a vector."""


def reconcile_database(database_name: str) -> tuple[int, int]:
    """``(vectors written, vectors removed)`` for one database's semantic layer.

    Raises :class:`UnembeddedRowsError` after removing the stale vectors when
    any changed row did not embed; it keeps its previous vector until a later
    run embeds it.
    """
    vdb = get_semantic_vdb()
    changed, current_ids = vdb.split_changed(semantic_rows(database_name))
    written = 0
    for chunk in batch_embed_chunks(changed, get_embed_params(), label=database_name):
        records = to_vdb_records(chunk)
        if records:
            written += vdb.run(records)
    removed = vdb.delete_missing(database_name, current_ids, labels=LABELS)
    logger.info(
        "Semantic vectors of %s: %d written, %d removed, %d unchanged",
        database_name,
        written,
        removed,
        len(current_ids) - len(changed),
    )
    if written < len(changed):
        raise UnembeddedRowsError(
            f"{len(changed) - written} of {len(changed)} changed rows of "
            f"{database_name} did not embed"
        )
    return written, removed


def reconcile_all() -> int:
    """Reconcile every database; returns how many databases failed."""
    failed = 0
    for database_name in database_names():
        try:
            reconcile_database(database_name)
        except Exception:
            failed += 1
            logger.exception(
                "Could not reconcile the semantic vectors of %s", database_name
            )
    return failed


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="embed")
    parser.add_argument("--database", help="reconcile only this database")
    args = parser.parse_args(argv)
    with pipeline_lease():
        if args.database:
            try:
                reconcile_database(args.database)
            except UnembeddedRowsError:
                logger.exception("Semantic vectors of %s", args.database)
                return 1
            return 0
        return 1 if reconcile_all() else 0
