# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Adding and removing the ontology's sources.

A source is stored under the database name its connector reports, because
ingestion files the catalog under that name and chat routes SQL by it. Adding
one therefore connects to it once, which also proves the data source works
before anything is stored.

``ontology.yaml`` lists the sources a new system starts with. They are stored
when the store has no source at all; after that the Sources page is the record,
so a source removed there stays removed.
"""

from __future__ import annotations

import logging
from typing import Any

from auto_ontology.connectors import hopsworks
from auto_ontology.connectors.registry import (
    create_connector,
    invalidate_connectors_cache,
)
from auto_ontology.dal import connections
from auto_ontology.hopsworks.config import OntologyConfig

logger = logging.getLogger(__name__)


def as_api(source: dict[str, Any]) -> dict[str, Any]:
    """A stored source in the API's shape, keyed by data source ``name``."""
    return {
        "name": source["data_source"],
        "schemas": source.get("schemas") or [],
        "table_regex": source.get("table_regex"),
        "database_name": source.get("database_name"),
    }


def list_sources() -> list[dict[str, Any]]:
    return [as_api(source) for source in connections.list_connections()]


def find_source(name: str) -> dict[str, Any] | None:
    """The stored source reading data source ``name``, or ``None``."""
    return next((source for source in list_sources() if source["name"] == name), None)


def add_source(
    name: str, schemas: list[str] | None = None, table_regex: str | None = None
) -> dict[str, Any]:
    """Store data source ``name`` as a source, or update its filters.

    Raises ``ValueError`` for an invalid source or one of an unsupported type,
    and the connector's error when the data source cannot be reached.
    """
    source = {"data_source": name, "schemas": schemas or [], "table_regex": table_regex}
    connector = create_connector(hopsworks.connection_string(source))
    try:
        database_name = connector.database_name
    finally:
        close = getattr(connector, "close", None)
        if close is not None:
            close()
    clash = next(
        (
            stored
            for stored in list_sources()
            if stored["database_name"] == database_name and stored["name"] != name
        ),
        None,
    )
    if clash is not None:
        raise ValueError(
            f"data source {name!r} reads database {database_name!r}, which "
            f"source {clash['name']!r} already reads"
        )
    connections.insert_connection(connection=source, database_name=database_name)
    invalidate_connectors_cache()
    return as_api({**source, "database_name": database_name})


def remove_source(name: str) -> str | None:
    """Detach source ``name``; returns its database name, or ``None`` when no
    source reads that data source. The catalog stays until a reset removes it."""
    source = find_source(name)
    if source is None:
        return None
    connections.clear_connection(database_name=source["database_name"])
    invalidate_connectors_cache()
    return source["database_name"]


def seed_sources(config: OntologyConfig) -> list[str]:
    """Store ``ontology.yaml``'s sources when the store has none; returns the
    names stored. A source that cannot be added is logged and skipped."""
    if connections.list_connections():
        return []
    added: list[str] = []
    for source in config.sources:
        try:
            add_source(source.name, list(source.schemas), source.table_regex)
        except Exception:
            logger.exception("Could not add source %r from ontology.yaml", source.name)
            continue
        added.append(source.name)
    return added
