# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""History of semantic compilation passes, and the progress of a running one.

The compile job records a start/end row for every pass and its stage and table
counts as it goes; the status endpoint reads the last successful -- and, if
more recent, the last failed -- pass back for the settings page.

``status`` is a nullable string outcome -- ``RUN_SUCCEEDED``, ``RUN_FAILED``,
or ``NULL``. A row is only ever written to when the pass reaches one of those
two terminal outcomes; there is no "aborted" value. ``NULL`` therefore covers
every other case -- still running, stopped, or killed with the job -- and
stays that way for a row nobody finishes. Whether a pass is running *now* is
the compile job's execution state in Hopsworks, not this table's.

Every function is best-effort: a store hiccup must not fail a pass or break the
status endpoint.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from auto_ontology.dal import schema as s
from auto_ontology.dal.schema import RUN_FAILED, RUN_SUCCEEDED
from auto_ontology.dal.session import get_engine, store
from auto_ontology.dal.types import utcnow

logger = logging.getLogger(__name__)

__all__ = [
    "RUN_FAILED",
    "RUN_SUCCEEDED",
    "get_last_failure_if_most_recent",
    "get_last_successful_run",
    "record_progress",
    "record_run_finish",
    "record_run_start",
]

_VALID_OUTCOMES = frozenset({RUN_SUCCEEDED, RUN_FAILED})
_history = s.semantic_compilation_history


def record_run_start() -> int | None:
    """Insert a row for a pass starting now; returns its id, or ``None`` on failure.

    Callers skip :func:`record_run_finish` when this returns ``None``, since
    there is no row to update.
    """
    try:
        with get_engine().begin() as connection:
            result = connection.execute(_history.insert().values(started_at=utcnow()))
            return int(result.inserted_primary_key[0])
    except Exception:
        logger.exception("Failed to record semantic compilation run start")
        return None


def record_progress(
    run_id: int | None, stage: str, done: int | None = None, total: int | None = None
) -> None:
    """Record where a running pass is; a no-op without a run id."""
    if run_id is None:
        return
    try:
        store().query_write(
            _history.update()
            .where(_history.c.id == run_id)
            .values(stage=stage, tables_done=done, tables_total=total)
        )
    except Exception:
        logger.exception(
            "Failed to record semantic compilation progress (id=%s)", run_id
        )


def record_run_finish(run_id: int | None, outcome: str | None) -> None:
    """Mark a started run as finished with *outcome*.

    ``None`` for *run_id* or *outcome* is a no-op, leaving the row as
    :func:`record_run_start` inserted it. Raises ``ValueError`` for an outcome
    other than ``RUN_SUCCEEDED``/``RUN_FAILED``.
    """
    if run_id is None or outcome is None:
        return
    if outcome not in _VALID_OUTCOMES:
        raise ValueError(f"invalid semantic compilation run outcome: {outcome!r}")
    try:
        store().query_write(
            _history.update()
            .where(_history.c.id == run_id)
            .values(finished_at=utcnow(), status=outcome)
        )
    except Exception:
        logger.exception(
            "Failed to record semantic compilation run finish (id=%s)", run_id
        )


def _isoformat(rows: list[dict]) -> str | None:
    if rows and rows[0]["finished_at"] is not None:
        return rows[0]["finished_at"].isoformat()
    return None


def get_last_successful_run() -> str | None:
    """ISO 8601 timestamp of the most recently finished successful pass, or ``None``."""
    try:
        return _isoformat(
            store().query_read(
                select(_history.c.finished_at)
                .where(_history.c.status == RUN_SUCCEEDED)
                .order_by(_history.c.finished_at.desc())
                .limit(1)
            )
        )
    except Exception:
        logger.exception("Failed to read last successful semantic compilation run")
        return None


def get_last_failure_if_most_recent() -> str | None:
    """ISO 8601 timestamp of the last failed pass, only if more recent than the
    last successful one; ``None`` otherwise.

    "Failed" means the pass ran and raised; a ``NULL`` status (running,
    stopped, killed) is not a verdict and never reads as a failure.
    """
    try:
        last_success = (
            select(func.max(_history.c.finished_at))
            .where(_history.c.status == RUN_SUCCEEDED)
            .scalar_subquery()
        )
        return _isoformat(
            store().query_read(
                select(_history.c.finished_at)
                .where(
                    _history.c.status == RUN_FAILED,
                    (last_success.is_(None)) | (_history.c.finished_at > last_success),
                )
                .order_by(_history.c.finished_at.desc())
                .limit(1)
            )
        )
    except Exception:
        logger.exception("Failed to read last failed semantic compilation run")
        return None
