# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The ontology's sources: the Hopsworks data sources its catalog is read from.

A source lives on its catalog database row, so the source and the catalog
database are the same record and cannot drift apart; the catalog name is the
source's identity. The row's ``connection`` holds::

    {"data_source": <Hopsworks data source name>,
     "schemas": [<schema to ingest>, ...],   # empty: every schema
     "table_regex": <regex a table name must match> | None}

and never credentials: a connector reads those from the data source with the
caller's Hopsworks identity when it is built.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select, update

from auto_ontology.catalog.table_filter import compile_pattern
from auto_ontology.dal import schema as s
from auto_ontology.dal.ops import upsert
from auto_ontology.dal.session import store

logger = logging.getLogger(__name__)

SOURCE_KEYS = frozenset({"data_source", "schemas", "table_regex"})


def _source(raw: Mapping[str, Any]) -> dict[str, Any]:
    """*raw* as a stored source. Raises ``ValueError`` on any other key, which
    is what keeps a host, user or password off the row."""
    unknown = set(raw) - SOURCE_KEYS
    if unknown:
        raise ValueError(
            f"a source holds only {sorted(SOURCE_KEYS)}, not {sorted(unknown)}: "
            "credentials come from the Hopsworks data source"
        )
    data_source = raw.get("data_source")
    if not isinstance(data_source, str) or not data_source.strip():
        raise ValueError("a source needs the name of a Hopsworks data source")
    schemas = raw.get("schemas") or []
    if not isinstance(schemas, list) or not all(
        isinstance(name, str) for name in schemas
    ):
        raise ValueError("a source's schemas are a list of schema names")
    table_regex = raw.get("table_regex") or None
    compile_pattern(table_regex, field="table_regex")
    return {
        "data_source": data_source.strip(),
        "schemas": [name.strip() for name in schemas if name.strip()],
        "table_regex": table_regex,
    }


def list_connections() -> list[dict[str, Any]]:
    """Every source, ordered by catalog database name.

    Each is the stored ``{"data_source", "schemas", "table_regex"}`` plus
    ``database_name``. A catalog database with no source, such as one a model
    import created, is skipped.
    """
    return [
        {**row["connection"], "database_name": row["name"]}
        for row in store().query_read(
            select(s.catalog_database.c.name, s.catalog_database.c.connection)
            .where(s.catalog_database.c.connection.isnot(None))
            .order_by(s.catalog_database.c.name)
        )
    ]


def insert_connection(
    *,
    connection: str | Mapping[str, Any],
    database_name: str,
) -> dict[str, Any]:
    """Set the source of a catalog database, creating the row if needed, and
    return the row.

    Creating it matters: a source is normally configured *before* anything is
    ingested, so there is usually no database row to attach to yet.
    *connection* is the source as a mapping or its JSON text. Raises
    ``ValueError`` when it is not a valid source (see the module docstring).
    """
    raw = json.loads(connection) if isinstance(connection, str) else connection
    if not isinstance(raw, Mapping):
        raise ValueError("a source is a JSON object")
    source = _source(raw)
    return upsert(
        s.catalog_database,
        {"name": database_name, "connection": source},
        key=["name"],
        set_=lambda inserted: {"connection": inserted.connection},
        returning=list(s.catalog_database.c),
    )[0]


def clear_connection(*, database_name: str) -> None:
    """Detach the source from the catalog database.

    The counterpart to :func:`insert_connection`, and the write that actually
    makes a database stop being a source — sources are exactly the catalog
    rows carrying a ``connection`` value.

    The row itself stays. The catalog hangs off it, so deleting it here would
    drop the ingested catalog while leaving behind the semantic rows and
    embeddings that are identified *through* it. Tearing those down is
    :func:`auto_ontology.dal.reset.delete_all_data`'s job.
    """
    store().query_write(
        update(s.catalog_database)
        .where(s.catalog_database.c.name == database_name)
        .values(connection=None)
    )


def verify_connectivity() -> None:
    """Probe the store. Raises if it is unreachable.

    Backs the health endpoint, so it must fail rather than report healthy — the
    ``SELECT 1`` is deliberately the cheapest statement that still proves a
    connection can be checked out of the pool and used.
    """
    store().query_read("SELECT 1")
