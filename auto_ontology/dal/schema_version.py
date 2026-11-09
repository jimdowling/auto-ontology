# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Is the database's schema the one this code expects?

Two callers, one rule. A job refuses to start when the answer is no, and
``/api/health`` reports it -- because the failure is otherwise invisible in the
worst way: the process starts and every catalog endpoint answers ``500`` with
nothing pointing at the cause.

The ontology app migrates at startup (:func:`auto_ontology.dal.migrations.migrate`)
and then checks; jobs only check, since the app is the store's one migrator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from auto_ontology.dal import migrations

logger = logging.getLogger(__name__)

_UPGRADE_ADVICE = "start the ontology app, which applies pending schema steps"


@dataclass(frozen=True)
class SchemaState:
    """What the database has recorded, against the steps this build has."""

    expected: str | None
    applied: str | None
    missing: tuple[str, ...] = ()
    #: Set when the recorded steps could not be read at all. Kept apart from
    #: ``missing`` because the advice differs: an unmigrated database is fixed
    #: by migrating, an unreachable one is not.
    unreachable: str | None = None

    @property
    def current(self) -> bool:
        """True only when every step this build has is recorded."""
        return self.unreachable is None and bool(self.expected) and not self.missing

    @property
    def detail(self) -> str:
        if self.unreachable is not None:
            return f"could not read the applied schema steps: {self.unreachable}"
        shown = ", ".join(self.missing[:5])
        more = f" and {len(self.missing) - 5} more" if len(self.missing) > 5 else ""
        return f"schema steps not applied: {shown}{more}. To fix: {_UPGRADE_ADVICE}"


def schema_state() -> SchemaState:
    """Compare the recorded steps against this build's. Never raises."""
    expected = [step.id for step in migrations.steps()]
    try:
        done = migrations.applied_steps()
    except Exception as exc:
        if _is_missing_table(exc):
            done = set()
        else:
            return SchemaState(
                expected=expected[-1],
                applied=None,
                unreachable=(str(exc) or type(exc).__name__)[:200],
            )
    missing = tuple(step for step in expected if step not in done)
    applied = next((step for step in reversed(expected) if step in done), None)
    return SchemaState(expected=expected[-1], applied=applied, missing=missing)


def _is_missing_table(exc: BaseException) -> bool:
    """Is this MySQL error 1146, "table doesn't exist", as opposed to "the database isn't"?"""
    seen: BaseException | None = exc
    while seen is not None:
        if getattr(seen, "args", None) and seen.args and seen.args[0] == 1146:
            return True
        seen = getattr(seen, "orig", None) or seen.__cause__ or seen.__context__
        if seen is exc:
            break
    return False


class SchemaOutOfDateError(RuntimeError):
    """The database's schema is not the one this build expects."""


def _raise_for(state: SchemaState) -> None:
    """The refusal message, as its own function so it can be tested.

    Split from :func:`require_current_schema` because the wording is the part
    that matters — it is the only thing an operator sees — and asserting on it
    should not require standing up a database in each of the failing states.
    """
    raise SchemaOutOfDateError(f"Refusing to start: {state.detail}")


def require_current_schema() -> None:
    """Raise unless every schema step this build has is recorded.

    Called at job start and after the app's own migration, so an operator gets
    one actionable line instead of a working ``/api/health`` and 500s elsewhere.
    """
    state = schema_state()
    if state.current:
        logger.info("Database schema is at the expected revision %s", state.applied)
        return
    _raise_for(state)
