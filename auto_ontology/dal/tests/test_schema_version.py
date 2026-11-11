# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The startup schema gate, and the states it has to tell apart.

The distinction that matters is between *unmigrated* and *unreachable*. Both
leave the build's steps unconfirmed, and conflating them tells an operator whose
database is down to migrate it — advice that cannot work. So the message is
asserted here, not just the pass/fail.

No database needed for most of this: the states are constructed directly, or
``applied_steps`` is replaced. The live path is covered by
``test_a_migrated_store_is_current``, which skips without a store.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("sqlalchemy")

import pymysql  # noqa: E402
from sqlalchemy.exc import ProgrammingError  # noqa: E402

from auto_ontology.dal import migrations  # noqa: E402
from auto_ontology.dal import schema_version as sv  # noqa: E402

_MISSING_TABLE = pymysql.err.ProgrammingError(
    1146, "Table 'ontology.schema_version' doesn't exist"
)
_REFUSED = pymysql.err.OperationalError(2003, "Can't connect to MySQL server")


def test_every_step_recorded_is_current() -> None:
    state = sv.SchemaState(expected="create:term", applied="create:term")
    assert state.current


def test_a_database_missing_steps_is_not_current_and_names_them() -> None:
    state = sv.SchemaState(
        expected="create:tag", applied="create:term", missing=("create:tag",)
    )
    assert not state.current
    assert "create:tag" in state.detail
    assert "start the ontology app" in state.detail


def test_a_long_missing_list_is_cut_to_five() -> None:
    missing = tuple(f"create:t{i}" for i in range(8))
    detail = sv.SchemaState(expected=missing[-1], applied=None, missing=missing).detail
    assert "create:t4" in detail
    assert "create:t5" not in detail
    assert "and 3 more" in detail


def test_an_unreachable_database_is_not_told_to_migrate() -> None:
    """The distinction this module exists to preserve.

    Telling someone to migrate a database nothing can connect to sends them
    down a path that cannot work, and hides the actual fault.
    """
    state = sv.SchemaState(
        expected="create:term", applied=None, unreachable="connection refused"
    )
    assert not state.current
    assert "could not read the applied schema steps" in state.detail
    assert "connection refused" in state.detail
    assert "start the ontology app" not in state.detail


def test_unknown_expected_step_is_not_treated_as_fine() -> None:
    """A packaging mistake that hides the steps must not read as healthy."""
    assert not sv.SchemaState(expected=None, applied="create:term").current


def test_require_current_schema_raises_with_an_actionable_message() -> None:
    state = sv.SchemaState(
        expected="create:term", applied=None, missing=("create:term",)
    )
    with pytest.raises(sv.SchemaOutOfDateError) as excinfo:
        sv._raise_for(state)
    message = str(excinfo.value)
    assert "Refusing to start" in message
    assert "start the ontology app" in message


def test_missing_table_is_distinguished_from_other_failures() -> None:
    """1146 is "table doesn't exist"; 1049, "unknown database", is not it."""
    assert sv._is_missing_table(_MISSING_TABLE)
    assert not sv._is_missing_table(_REFUSED)
    assert not sv._is_missing_table(
        pymysql.err.OperationalError(1049, "Unknown database 'ontology'")
    )


def test_missing_table_is_found_through_a_wrapped_exception() -> None:
    """SQLAlchemy wraps the driver error, so the cause chain has to be walked."""
    wrapped = ProgrammingError("SELECT step FROM schema_version", {}, _MISSING_TABLE)
    assert sv._is_missing_table(wrapped)


def test_a_missing_schema_version_table_means_nothing_applied(monkeypatch) -> None:
    def missing() -> set[str]:
        raise ProgrammingError("SELECT step FROM schema_version", {}, _MISSING_TABLE)

    monkeypatch.setattr(sv.migrations, "applied_steps", missing)
    state = sv.schema_state()

    assert state.unreachable is None
    assert state.applied is None
    assert state.missing == tuple(step.id for step in migrations.steps())


def test_an_unreadable_store_is_unreachable(monkeypatch) -> None:
    def refused() -> set[str]:
        raise _REFUSED

    monkeypatch.setattr(sv.migrations, "applied_steps", refused)
    state = sv.schema_state()

    assert not state.current
    assert state.unreachable is not None
    assert "Can't connect" in state.unreachable


def test_schema_state_reports_the_steps_still_to_apply(monkeypatch) -> None:
    ids = [step.id for step in migrations.steps()]
    monkeypatch.setattr(sv.migrations, "applied_steps", lambda: set(ids[:-2]))
    state = sv.schema_state()

    assert not state.current
    assert state.missing == tuple(ids[-2:])
    assert state.applied == ids[-3]
    assert state.expected == ids[-1]


def test_a_migrated_store_is_current() -> None:
    """Against the session's migrated store, every step is recorded."""
    if not os.environ.get("MYSQL_USER"):
        pytest.skip("MYSQL_* not set")
    state = sv.schema_state()
    if state.unreachable is not None:
        pytest.skip(f"store unreachable: {state.unreachable}")
    assert state.current, state.detail
