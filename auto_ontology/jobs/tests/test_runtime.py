# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The pipeline lease, on the test store."""

from __future__ import annotations

import os
from datetime import timedelta

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("MYSQL_USER"), reason="MYSQL_* not set"
)


@pytest.fixture(autouse=True)
def _clean() -> None:
    from auto_ontology.dal import schema as s
    from auto_ontology.dal.session import store

    store().query_write(s.job_lease.delete())


def test_one_holder_at_a_time() -> None:
    from auto_ontology.jobs.runtime import acquire, release, renew

    assert acquire("pipeline", "ingest#1")
    assert not acquire("pipeline", "compile#2")
    assert renew("pipeline", "ingest#1")
    assert not renew("pipeline", "compile#2")
    release("pipeline", "ingest#1")
    assert acquire("pipeline", "compile#2")


def test_an_expired_lease_can_be_taken_over() -> None:
    from auto_ontology.dal import schema as s
    from auto_ontology.dal.session import store
    from auto_ontology.dal.types import utcnow
    from auto_ontology.jobs.runtime import acquire

    assert acquire("pipeline", "killed#1")
    store().query_write(
        s.job_lease.update().values(expires_at=utcnow() - timedelta(seconds=1))
    )
    assert acquire("pipeline", "next#2")


def test_the_context_manager_releases_on_error() -> None:
    from auto_ontology.jobs.runtime import LeaseHeldError, acquire, pipeline_lease

    with pytest.raises(RuntimeError, match="boom"):
        with pipeline_lease():
            raise RuntimeError("boom")
    assert acquire("pipeline", "after#3")
    with pytest.raises(LeaseHeldError):
        with pipeline_lease():
            pass
