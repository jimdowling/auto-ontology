# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""API routes that run, reset and report semantic compilation.

Running and resetting start the ontology's compile and reset jobs.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from auto_ontology.dal.terms import semantic_layer_calculated
from auto_ontology.ingestion_service.history import (
    get_last_failure_if_most_recent,
    get_last_successful_run,
)
from auto_ontology.server.ingestion.proxy import (
    is_semantic_compilation_running,
    trigger_semantic_compile,
    trigger_semantic_reset,
)
from auto_ontology.server.responses import SemanticStatusResponse, StatusResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/semantic-compilation/trigger", status_code=202, response_model=StatusResponse
)
async def trigger() -> dict[str, str]:
    """Start a compile run now, unless one is already queued or running."""
    trigger_semantic_compile()
    return {"status": "accepted"}


@router.post(
    "/semantic-compilation/reset", status_code=202, response_model=StatusResponse
)
async def reset() -> dict[str, str]:
    """Start the reset job for every database's semantic layer.

    The job deletes the semantic rows and vectors and compiles them again, so
    the layer is rebuilt without waiting for the next scheduled run.
    """
    trigger_semantic_reset()
    return {"status": "accepted"}


@router.get("/semantic-compilation/status", response_model=SemanticStatusResponse)
def semantic_status() -> dict[str, bool | str | None]:
    """Report whether the semantic layer has been calculated (any Term exists),
    whether a compile job is queued or running, when the last pass completed
    successfully, and when it last failed.

    ``running`` reads the compile job's executions and degrades to ``False``
    when Hopsworks cannot be asked; the timestamps come from the
    ``semantic_compilation_history`` table.
    """
    return {
        "calculated": semantic_layer_calculated(),
        "running": is_semantic_compilation_running(),
        "last_success_at": get_last_successful_run(),
        "last_failure_at": get_last_failure_if_most_recent(),
    }
