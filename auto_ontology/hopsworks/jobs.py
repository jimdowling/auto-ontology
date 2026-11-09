# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Starting the ontology's Hopsworks jobs from the app.

The ingest, compile, embed, reset and import jobs are named in
``ontology.yaml``. A job the app starts runs as the app's starter, with that
member's credentials. Starting a job that already has an execution queued or
running does nothing, so repeated edits collapse into one embed run and a
second Compile click does not start a second compile.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Execution states that mean a run is pending or under way.
ACTIVE_STATES = frozenset(
    {
        "INITIALIZING",
        "INITIALIZATION_FAILED",
        "SUBMITTED",
        "RUNNING",
        "AGGREGATING_LOGS",
        "STARTING_APP_MASTER",
        "APP_MASTER_START_FAILED",
        "PENDING",
        "NEW",
        "NEW_SAVING",
        "ACCEPTED",
        "STOPPING",
    }
)


class UnknownJobError(KeyError):
    """``ontology.yaml`` names no job for that pipeline step."""


def _job(step: str) -> Any:
    from auto_ontology.hopsworks.client import login
    from auto_ontology.hopsworks.config import load

    name = load().jobs.get(step)
    if not name:
        raise UnknownJobError(step)
    return login().get_job_api().get_job(name)


def _latest_state(job: Any) -> str | None:
    executions = job.get_executions()
    if not executions:
        return None
    latest = max(executions, key=lambda execution: execution.submission_time or "")
    return str(latest.state).upper()


def is_running(step: str) -> bool:
    """Whether ``step``'s job has an execution queued or running. False on any error."""
    try:
        return _latest_state(_job(step)) in ACTIVE_STATES
    except Exception:
        logger.exception("Could not read the state of the %s job", step)
        return False


def run_arguments(job: Any, args: str | None) -> str | None:
    """``args`` after the job's default arguments, which carry ``--config``.

    Hopsworks runs an execution with its own arguments *instead of* the
    defaults, so extra arguments must repeat them.
    """
    defaults = ((job.config or {}).get("defaultArgs") or "").strip()
    if not args:
        return None
    return f"{defaults} {args}".strip()


def start_pipeline_job(step: str, args: str | None = None) -> bool:
    """Start ``step``'s job unless it already has an active execution.

    Returns whether a run was started. Raises :class:`UnknownJobError` for a
    step ``ontology.yaml`` does not name, and whatever the hopsworks client
    raises when the job cannot be started.
    """
    job = _job(step)
    if _latest_state(job) in ACTIVE_STATES:
        logger.info("The %s job is already active; not starting another run", step)
        return False
    job.run(args=run_arguments(job, args), await_termination=False)
    logger.info("Started the %s job", step)
    return True
