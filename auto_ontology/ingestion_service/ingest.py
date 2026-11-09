# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

from auto_ontology.utils import get_embed_params
from auto_ontology.utils.embedding import batch_embed_chunks
from auto_ontology.utils.embedding_rows import (
    CatalogEmbeddingRowsOp,
)
from auto_ontology.connectors.base import SQLDatabase

from auto_ontology.catalog import ingest_catalog
from auto_ontology.vdb import get_data_vdb
from auto_ontology.vdb.records import to_vdb_records
from auto_ontology.infra.feature_flags import is_pii_detection_enabled
from auto_ontology.ingestion_service.pii import run_pii_propagation
from auto_ontology.pii_detection.service import detect_and_tag_pii

logger = logging.getLogger("ingestion_service.ingest")


@contextmanager
def _shared_connection(connector: SQLDatabase) -> Iterator[None]:
    """Hold one connection open for the whole extraction, where supported.

    Introspection issues a statement per table, and on Databricks opening a connection
    is both the slowest step (~0.9s) and the flakiest — measured hanging for minutes,
    and sometimes never completing. Paying that once per run instead of once per
    statement removes the dominant cost and the dominant failure mode.

    Connectors without the hook are used unchanged.
    """
    reuse = getattr(connector, "reuse_connection", None)
    if reuse is None:
        yield
        return
    with reuse():
        yield


def _row_count(frame: Any) -> int:
    """Row count for a possibly-``None`` DataFrame.

    Kept defensive on purpose: this only feeds a log line, and a completion log
    that raises would turn a successful ingest into a failed one.
    """
    try:
        return 0 if frame is None else len(frame)
    except TypeError:
        return 0


def _run_pii_detection(columns_df: Any, database_name: str) -> None:
    """Enrich persisted columns without making catalog ingestion depend on it."""

    try:
        detect_and_tag_pii(columns_df)
    except Exception:
        logger.exception(
            "PII detection failed for database %s; catalog ingestion will "
            "continue. Unprocessed columns will be retried on the next ingest",
            database_name,
        )
    run_pii_propagation(database_name)


def _as_rows(embed_rows: Any) -> list[dict[str, Any]]:
    if hasattr(embed_rows, "to_dict"):
        return embed_rows.to_dict(orient="records")
    return list(embed_rows or [])


def run_ingest(connector: SQLDatabase) -> None:
    """Extract, embed, and persist a connector's tabular catalog.

    The connector's lifecycle is owned by the caller — ``run_ingest`` does not
    close it, since the ingest job reuses cached connectors from
    :func:`auto_ontology.connectors.registry.get_connectors`.

    Three straight-line steps: the catalog write
    (:func:`auto_ontology.catalog.ingest_catalog`), the embedding rows
    (:class:`~auto_ontology.utils.embedding_rows.CatalogEmbeddingRowsOp`), and
    the embed step (:func:`auto_ontology.utils.embedding.batch_embed_chunks`).

    Embedding is the long pole — minutes of remote round trips against tens of
    seconds for everything else — so its chunks are written to the vector
    feature group as they arrive rather than buffered into one DataFrame. That keeps peak memory to a
    chunk, overlaps the write with the next chunk's embed, and means a failure
    three minutes in has already persisted most of the catalog.
    """
    if connector is None:
        raise ValueError("Connector is not set")

    database_name = connector.database_name
    embed_params = get_embed_params()

    started = time.monotonic()
    logger.info("Data ingestion started for database %s", database_name)

    with _shared_connection(connector):
        tables_df, columns_df = ingest_catalog(connector)

    if is_pii_detection_enabled():
        _run_pii_detection(columns_df, database_name)
    else:
        logger.info(
            "PII detection skipped for database %s (disabled in settings)",
            database_name,
        )

    embed_rows = CatalogEmbeddingRowsOp(database_name=database_name)(
        (tables_df, columns_df)
    )

    # Only rows whose text changed since they were last embedded are sent to
    # the embedding endpoint; vectors of tables and columns that are gone are
    # removed afterwards, so a failed embed leaves the previous vectors in place.
    data_vdb = get_data_vdb()
    changed_rows, current_ids = data_vdb.split_changed(_as_rows(embed_rows))
    rows_written = 0
    for chunk in batch_embed_chunks(changed_rows, embed_params, label=database_name):
        records = to_vdb_records(chunk)
        if records:
            rows_written += data_vdb.run(records)
    removed = data_vdb.delete_missing(database_name, current_ids)
    if removed:
        logger.info(
            "Removed %d vectors of tables and columns no longer in %s",
            removed,
            database_name,
        )

    if rows_written:
        logger.info(
            "Tabular ingest result: %d changed rows embedded and written", rows_written
        )
    else:
        # An empty result is normal for a catalog that has not changed, but it
        # is also what a broken embed step produces, so it is worth a line.
        logger.info(
            "No changed rows embedded for database %s (expected when the catalog "
            "is unchanged)",
            database_name,
        )

    # Only reached when every step above succeeded: each one raises rather than
    # returning a failure, and nothing here catches. So this line means the run
    # is genuinely complete, not merely over.
    logger.info(
        "Data ingestion finished successfully for database %s — "
        "%d table(s), %d column(s), %d embedding row(s) in %.1fs",
        database_name,
        _row_count(tables_df),
        _row_count(columns_df),
        rows_written,
        time.monotonic() - started,
    )
