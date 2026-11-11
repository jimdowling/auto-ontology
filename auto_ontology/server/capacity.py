# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""How many agent runs this app pod serves at once.

Chat streams and entity-coverage calls share the cap: each chat run holds a
spawned worker process and both hold model-serving requests, and the app runs
as a single replica. A request beyond the cap gets 429 instead of queueing.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException

MAX_RUNS = int(os.environ.get("ONTOLOGY_MAX_CONCURRENT_RUNS", "4"))
RETRY_AFTER_SECONDS = 5

_runs = threading.BoundedSemaphore(MAX_RUNS)


def acquire() -> None:
    """Take a run slot; raises 429 when all :data:`MAX_RUNS` are taken.

    Every successful call must be paired with exactly one :func:`release`.
    """
    if not _runs.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail=f"The assistant is answering {MAX_RUNS} questions already; try again shortly",
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        )


def release() -> None:
    _runs.release()


@contextmanager
def run_slot() -> Iterator[None]:
    acquire()
    try:
        yield
    finally:
        release()
