# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Connection and transaction scope for the DAL's store (RonDB over MySQL).

Two entry points, used by every read and write in the DAL:

* :func:`store` returns the active transaction if there is one, otherwise a
  handle that runs each statement in its own autocommitted transaction — the
  same split the DAL relies on for single-statement writes.
* :func:`write_transaction` makes every statement in the block one unit of
  work. Nesting reuses the outermost scope, so a routine that calls another
  transactional routine still commits once.

**Pooling.** The DAL is called from three places with different concurrency
shapes: FastAPI request handlers, ingestion ``ThreadPoolExecutor`` threads
(``write_to_graph`` fans out), and a *spawned* chat-worker subprocess
(:mod:`auto_ontology.server.chat.worker`). SQLAlchemy's ``QueuePool`` is thread-safe, and
the ``ContextVar`` holding the active transaction is per-thread and per-task, so
two threads inside ``write_transaction`` get genuinely separate transactions
rather than trampling one connection.

The subprocess is the case worth naming: a pool cannot be inherited across a
fork, and file descriptors carried into a child produce corruption that only
shows under load. :func:`dispose_engine` exists for that reason and is called on
process boundaries; ``spawn`` (which is what the worker uses) starts a fresh
interpreter and so builds its own engine anyway.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import Engine

from auto_ontology.infra.mysql import mysql_url

logger = logging.getLogger(__name__)

# Callers that expand an ``IN`` list of catalog ids stay at this size, which
# keeps each statement well under RonDB's 32768-row transaction cap when it
# writes. Read at call time so tests can shrink it without rewriting queries.
IN_QUERY_BATCH = 1000

_engine: Engine | None = None
_active: ContextVar[StoreConn | None] = ContextVar("_active_store_conn", default=None)


def get_engine() -> Engine:
    """The process-wide engine, built on first use."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            mysql_url(),
            pool_size=int(os.environ.get("AUTO_ONTOLOGY_DB_POOL_SIZE", "5")),
            max_overflow=int(os.environ.get("AUTO_ONTOLOGY_DB_MAX_OVERFLOW", "5")),
            # Recycle below any middlebox idle timeout, and check liveness
            # before handing a connection out. Without pre_ping, a connection
            # killed server-side surfaces as a failed query on an unrelated
            # request rather than as a reconnect. Hopsworks also kills the app
            # user's sessions when it rotates its password on an app start.
            pool_recycle=1800,
            pool_pre_ping=True,
            # A blackholed database hangs a TCP connect rather than refusing it;
            # without a bound every request that touches the store holds its
            # worker and the pool drains. `/api/health` is the readiness probe
            # and must return to report "degraded".
            connect_args={"connect_timeout": 3},
            future=True,
        )
    return _engine


def dispose_engine() -> None:
    """Close every pooled connection. Idempotent.

    Called from ``auto_ontology.dal.close_store()`` on shutdown, and before handing a
    process to a child, since pooled sockets must not be shared across a fork.
    """
    global _engine
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            logger.warning("dispose_engine: engine failed to dispose", exc_info=True)
        finally:
            _engine = None


def _rows(result: Any) -> list[dict[str, Any]]:
    """Normalise a result to ``list[dict]``."""
    if result.returns_rows:
        return [dict(row) for row in result.mappings()]
    return []


class StoreConn:
    """A thin handle over a SQLAlchemy connection.

    The ``query_read`` / ``query_write`` split is naming only: it documents
    intent at the call site, and the store needs no routing hint.
    """

    def __init__(self, connection: Connection | None = None) -> None:
        self._connection = connection

    def query(
        self, statement: Any, parameters: dict[str, Any] | None = None, **_: Any
    ) -> list[dict[str, Any]]:
        compiled = text(statement) if isinstance(statement, str) else statement
        if self._connection is not None:
            return _rows(self._connection.execute(compiled, parameters or {}))
        # No open transaction: one autocommitted statement, connection returned
        # to the pool immediately. This is why a multi-statement write that
        # must be all-or-nothing has to go through write_transaction().
        with (
            get_engine()
            .connect()
            .execution_options(isolation_level="AUTOCOMMIT") as connection
        ):
            return _rows(connection.execute(compiled, parameters or {}))

    def query_read(
        self, statement: Any, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        return self.query(statement, parameters)

    def query_write(
        self, statement: Any, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        return self.query(statement, parameters)


def store() -> StoreConn:
    """Return the active transaction, or an autocommitting handle."""
    active = _active.get()
    return active if active is not None else StoreConn()


@contextmanager
def write_transaction() -> Iterator[None]:
    """Run every :func:`store` query in the block in one transaction.

    Commits on clean exit, rolls back on any exception. Nesting reuses the
    outermost transaction so the whole block stays a single unit of work.
    """
    if _active.get() is not None:
        yield
        return

    with get_engine().connect() as connection:
        transaction = connection.begin()
        token = _active.set(StoreConn(connection))
        try:
            yield
        except BaseException:
            transaction.rollback()
            raise
        else:
            transaction.commit()
        finally:
            _active.reset(token)
