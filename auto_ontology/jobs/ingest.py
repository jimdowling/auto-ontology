# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read the sources into the catalog and embed what changed.

Stores ``ontology.yaml``'s sources first when the store has none
(:func:`auto_ontology.connectors.sources.seed_sources`), then ingests every
source, or only ``--source <data source name>``. A failure in one source does
not stop the others. Afterwards the tagging rules are replayed and, when
semantic compilation is switched on, the compile job is started, so a new
source reaches chat without waiting for the nightly compile. The exit code is
non-zero when any source failed.
"""

from __future__ import annotations

import argparse
import logging

from auto_ontology.jobs.runtime import pipeline_lease

logger = logging.getLogger(__name__)


def ingest_sources(only: str | None = None) -> tuple[int, int]:
    """Ingest every source, or only data source ``only``; returns (succeeded, failed)."""
    from auto_ontology.connectors.registry import get_connectors
    from auto_ontology.connectors.sources import list_sources
    from auto_ontology.ingestion_service.ingest import run_ingest

    databases = {
        source["database_name"]
        for source in list_sources()
        if only is None or source["name"] == only
    }
    if only is not None and not databases:
        raise ValueError(f"no source reads data source {only!r}")
    connectors = {
        connector.database_name: connector
        for connector in get_connectors()
        if connector.database_name in databases
    }
    succeeded = failed = 0
    for database_name in sorted(databases):
        connector = connectors.get(database_name)
        if connector is None:
            logger.error(
                "Source %s has no connector; see the error above", database_name
            )
            failed += 1
            continue
        try:
            run_ingest(connector)
        except Exception:
            logger.exception("Ingest of %s failed", database_name)
            failed += 1
            continue
        succeeded += 1
    return succeeded, failed


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ingest")
    parser.add_argument("--source", help="ingest only this data source")
    args = parser.parse_args(argv)

    from auto_ontology.connectors.sources import seed_sources
    from auto_ontology.hopsworks.config import load
    from auto_ontology.ingestion_service.config import is_semantic_compilation_enabled
    from auto_ontology.ingestion_service.rules import replay_rules

    with pipeline_lease():
        seeded = seed_sources(load())
        if seeded:
            logger.info("Added the sources from ontology.yaml: %s", ", ".join(seeded))
        succeeded, failed = ingest_sources(args.source)
        if succeeded:
            replay_rules("ingest")
    logger.info("Ingest finished: %d source(s) succeeded, %d failed", succeeded, failed)

    # After the lease is released: the compile job takes it in its own pod.
    if succeeded and is_semantic_compilation_enabled():
        from auto_ontology.hopsworks.jobs import start_pipeline_job

        try:
            start_pipeline_job("compile")
        except Exception:
            logger.exception("Could not start the compile job")
    return 1 if failed else 0
