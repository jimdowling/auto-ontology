# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""What every pipeline job shares: the schema check and the pipeline lease.

The lease is one row in ``job_lease``. A job takes it when the row is absent or
expired, renews it every :data:`RENEW_SECONDS` from a background thread, and
deletes it when done. A job killed with its pod stops renewing, so its lease
expires after :data:`LEASE_SECONDS` and the next run proceeds. The lease is not
an NDB transaction held open: those time out long before a compile finishes.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import or_, select

from auto_ontology.dal import schema as s
from auto_ontology.dal.schema_version import require_current_schema
from auto_ontology.dal.session import store, write_transaction
from auto_ontology.dal.types import utcnow

logger = logging.getLogger(__name__)

PIPELINE_LEASE = "pipeline"
LEASE_SECONDS = 600
RENEW_SECONDS = 120


class LeaseHeldError(RuntimeError):
    """Another pipeline job holds the lease."""


def _holder() -> str:
    execution = os.environ.get("HOPSWORKS_JOB_EXECUTION_ID", "local")
    return f"{os.environ.get('HOPSWORKS_JOB_NAME', 'job')}#{execution}@{socket.gethostname()}"


def acquire(name: str, holder: str) -> bool:
    """Take the lease if it is free or expired; returns whether this holder has it."""
    now = utcnow()
    expires = now + timedelta(seconds=LEASE_SECONDS)
    lease = s.job_lease
    with write_transaction():
        rows = store().query_read(
            select(lease.c.holder, lease.c.expires_at)
            .where(lease.c.name == name)
            .with_for_update()
        )
        if not rows:
            store().query_write(
                lease.insert().values(name=name, holder=holder, expires_at=expires)
            )
            return True
        if rows[0]["holder"] != holder and rows[0]["expires_at"] > now:
            return False
        store().query_write(
            lease.update()
            .where(lease.c.name == name)
            .values(holder=holder, expires_at=expires)
        )
        return True


def renew(name: str, holder: str) -> bool:
    """Extend the lease; returns False when this holder no longer has it."""
    lease = s.job_lease
    with write_transaction():
        rows = store().query_read(
            select(lease.c.name)
            .where(lease.c.name == name, lease.c.holder == holder)
            .with_for_update()
        )
        if not rows:
            return False
        store().query_write(
            lease.update()
            .where(lease.c.name == name)
            .values(expires_at=utcnow() + timedelta(seconds=LEASE_SECONDS))
        )
        return True


def release(name: str, holder: str) -> None:
    store().query_write(
        s.job_lease.delete().where(
            s.job_lease.c.name == name,
            or_(s.job_lease.c.holder == holder, s.job_lease.c.expires_at < utcnow()),
        )
    )


@contextmanager
def pipeline_lease() -> Iterator[None]:
    """Hold the pipeline lease for the block. Raises :class:`LeaseHeldError`
    when another job holds it, and the schema error when the schema is behind."""
    require_current_schema()
    holder = _holder()
    if not acquire(PIPELINE_LEASE, holder):
        raise LeaseHeldError("another ontology pipeline job is running")
    stop = threading.Event()

    def keep_alive() -> None:
        while not stop.wait(RENEW_SECONDS):
            try:
                if not renew(PIPELINE_LEASE, holder):
                    logger.error("Lost the pipeline lease to another holder")
                    return
            except Exception:
                logger.exception("Could not renew the pipeline lease")

    renewer = threading.Thread(target=keep_alive, name="pipeline-lease", daemon=True)
    renewer.start()
    try:
        yield
    finally:
        stop.set()
        renewer.join(timeout=5)
        release(PIPELINE_LEASE, holder)
