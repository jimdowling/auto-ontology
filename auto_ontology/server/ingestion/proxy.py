# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Requests from the API to the ontology's pipeline jobs.

Upstream these were HTTP calls to a separate ingestion service; on Hopsworks
each is a job run (:mod:`auto_ontology.hopsworks.jobs`). Every trigger is
best-effort, as before: a failure to start a run is logged and never fails the
request that asked for it, since the scheduled runs catch up anyway.
"""

from __future__ import annotations

import logging
import shlex
from typing import Any

from auto_ontology.hopsworks import jobs

logger = logging.getLogger(__name__)


def _start(step: str, args: str | None = None) -> None:
    try:
        jobs.start_pipeline_job(step, args)
    except Exception:
        logger.exception("Could not start the %s job", step)


def trigger_ingest(connection: dict[str, Any]) -> None:
    """Ingest the source that was just added or changed."""
    source = connection.get("data_source") or connection.get("database_name")
    _start("ingest", f"--source {shlex.quote(source)}" if source else None)


def trigger_semantic_compile() -> None:
    _start("compile")


def is_semantic_compilation_running() -> bool:
    return jobs.is_running("compile")


def trigger_semantic_reset(database_name: str | None = None) -> None:
    """Rebuild the semantic layer of one database, or of all of them."""
    args = "--semantic"
    if database_name:
        args += f" --database {shlex.quote(database_name)}"
    _start("reset", args)


def trigger_reset(database_name: str) -> None:
    """Remove a deleted source's catalog, semantic layer and vectors."""
    _start("reset", f"--all --database {shlex.quote(database_name)}")


def trigger_embed() -> None:
    """Reconcile vectors after edits; repeated calls collapse into one run."""
    _start("embed")
