# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The readiness checks of the store and its schema.

Neither raises. A readiness endpoint has to answer *because* a dependency is
down; turning that into a 500 loses the distinction between "not ready" and
"broken", which is the whole signal.
"""

from __future__ import annotations

from auto_ontology.dal.connections import verify_connectivity
from auto_ontology.dal.schema_version import schema_state


def check_store() -> dict[str, str]:
    """Probe the pooled connection the application actually uses.

    Through the DAL rather than a fresh connection: a raw connection
    proves the server is reachable, which is not the same as proving this
    process can get a usable connection out of its pool — and the pool is what
    every request depends on.
    """
    try:
        verify_connectivity()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": (str(exc) or type(exc).__name__)[:200]}


def check_schema() -> dict[str, str]:
    """Report whether the database has every schema step this build expects.

    The app refuses to *start* on a stale schema, so in practice this catches
    the case that gate cannot: a schema that changes under a running process,
    such as a table dropped by hand.
    """
    state = schema_state()
    if state.current:
        return {"status": "ok", "revision": state.applied or ""}
    return {"status": "error", "detail": state.detail[:200]}
