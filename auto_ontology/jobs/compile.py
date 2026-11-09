# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compile the semantic layer of every ingested database.

One pass compiles each database in turn (a failure in one does not stop the
others), reconciles the semantic vectors, propagates PII tags to the new
attributes, and replays the tagging rules. The pass is recorded in
``semantic_compilation_history`` with its stage as it goes. A pass is skipped
while semantic compilation is switched off in Settings, unless ``--force``.
The exit code is non-zero when any database failed.
"""

from __future__ import annotations

import argparse
import logging
import time

from auto_ontology.ingestion_service.config import is_semantic_compilation_enabled
from auto_ontology.ingestion_service.history import (
    RUN_FAILED,
    RUN_SUCCEEDED,
    record_progress,
    record_run_finish,
    record_run_start,
)
from auto_ontology.ingestion_service.pii import run_pii_propagation
from auto_ontology.ingestion_service.rules import replay_rules
from auto_ontology.jobs import embed
from auto_ontology.jobs.runtime import pipeline_lease
from auto_ontology.semantic.compile import run_semantic_compilation

logger = logging.getLogger(__name__)


def compile_all() -> bool:
    """Run one compilation pass; returns whether every database succeeded."""
    databases = embed.database_names()
    if not databases:
        logger.info("Nothing to compile: no source has been ingested yet")
        return True
    run_id = record_run_start()
    outcome = RUN_SUCCEEDED
    started = time.monotonic()
    try:
        for index, database_name in enumerate(databases):
            record_progress(run_id, f"compiling {database_name}", index, len(databases))
            try:
                tables = run_semantic_compilation(database_name)
                logger.info("Compiled %d table(s) of %s", tables, database_name)
            except Exception:
                outcome = RUN_FAILED
                logger.exception("Compilation failed for database %s", database_name)
        record_progress(run_id, "reconciling vectors", len(databases), len(databases))
        if embed.reconcile_all():
            outcome = RUN_FAILED
        record_progress(run_id, "tagging", len(databases), len(databases))
        run_pii_propagation("compile")
        replay_rules("compile")
    except Exception:
        outcome = RUN_FAILED
        raise
    finally:
        record_run_finish(run_id, outcome)
        logger.info(
            "Compilation pass %s over %d database(s) in %.1fs",
            outcome,
            len(databases),
            time.monotonic() - started,
        )
    return outcome == RUN_SUCCEEDED


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="compile")
    parser.add_argument(
        "--force", action="store_true", help="compile even when switched off"
    )
    args = parser.parse_args(argv)
    with pipeline_lease():
        if not args.force and not is_semantic_compilation_enabled():
            logger.info("Semantic compilation is switched off in Settings; skipping")
            return 0
        return 0 if compile_all() else 1
