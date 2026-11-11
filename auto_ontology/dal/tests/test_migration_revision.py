# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The migration runner's steps, and that a run is idempotent and resumable.

The steps are derived from the schema, so what can go wrong is their order and
their bookkeeping: a table created before a table it references, two steps
sharing an id (the second would never run), a run that redoes or skips work
after an interruption. The live tests drive :func:`migrations.migrate` with a
DDL double that records what it is asked to do, against the session's real
``schema_version`` table; every table already exists, so recording a create
step without running it is the truth.
"""

from __future__ import annotations

import os
import re

import pytest

pytest.importorskip("sqlalchemy")

from auto_ontology.dal import migrations  # noqa: E402
from auto_ontology.dal import schema as s  # noqa: E402
from auto_ontology.dal.schema_version import schema_state  # noqa: E402
from auto_ontology.dal.session import store  # noqa: E402


def test_step_ids_are_unique() -> None:
    ids = [step.id for step in migrations.steps()]
    assert len(ids) == len(set(ids))


def test_schema_version_comes_first() -> None:
    """Every later step is recorded in it, so it has to exist before them."""
    first = migrations.steps()[0]
    assert (first.kind, first.table) == ("create", s.schema_version.name)


def test_every_table_has_one_create_step() -> None:
    created = [step.table for step in migrations.steps() if step.kind == "create"]
    assert sorted(created) == sorted(s.METADATA.tables)


def test_a_table_is_created_after_every_table_it_references() -> None:
    """A create carries its foreign keys, which MySQL checks on the spot."""
    position = {
        step.table: index
        for index, step in enumerate(migrations.steps())
        if step.kind == "create"
    }
    for name, table in s.METADATA.tables.items():
        for foreign_key in table.foreign_keys:
            parent = foreign_key.column.table.name
            if parent != name:
                assert position[parent] < position[name], f"{name} before {parent}"


def test_every_string_column_states_its_character_set() -> None:
    """The project's online database on Hopsworks does not default to utf8mb4."""
    bare = re.compile(r"\b(VARCHAR\(\d+\)|MEDIUMTEXT|TEXT)(?! CHARACTER SET)")
    for step in migrations.steps():
        assert not bare.search(step.sql), step.id


def test_a_create_carries_the_tables_indexes() -> None:
    term = next(step for step in migrations.steps() if step.table == s.term.name)
    assert "INDEX `ix_term_name` (`name`)" in term.sql
    assert "UNIQUE (name, source)" in term.sql


# --------------------------------------------------------------------------
# Against the session's store
# --------------------------------------------------------------------------


class RecordingDDL:
    """Records each create and alteration; refuses the one ``fail_on`` names."""

    def __init__(self, fail_on: migrations.Step | None = None) -> None:
        self.fail_on = fail_on
        self.calls: list[str] = []

    def _run(self, name: str, sql: str) -> None:
        if self.fail_on is not None and (name, sql) == (
            self.fail_on.table,
            self.fail_on.sql,
        ):
            raise RuntimeError(f"refused {self.fail_on.id}")
        self.calls.append(name)

    def create_table(self, name: str, definition: str) -> None:
        self._run(name, definition)

    def alter_table(self, name: str, alteration: str) -> None:
        self._run(name, alteration)


@pytest.fixture
def recorded_steps():
    """The session's ``schema_version``, put back whole however the test ends."""
    if not os.environ.get("MYSQL_USER"):
        pytest.skip("MYSQL_* not set")
    yield
    migrations.migrate(RecordingDDL())
    assert schema_state().current


def _forget(steps: list[migrations.Step]) -> None:
    store().query_write(
        s.schema_version.delete().where(
            s.schema_version.c.step.in_([step.id for step in steps])
        )
    )


def test_migrate_is_idempotent(recorded_steps) -> None:
    ddl = RecordingDDL()
    assert migrations.migrate(ddl) == []
    assert ddl.calls == [s.schema_version.name]


def test_migrate_resumes_after_a_failure(recorded_steps) -> None:
    """The steps before the failure stay recorded; the next run starts at it."""
    tail = migrations.steps()[-3:]
    _forget(tail)

    with pytest.raises(RuntimeError, match=tail[1].id):
        migrations.migrate(RecordingDDL(fail_on=tail[1]))
    recorded = migrations.applied_steps()
    assert tail[0].id in recorded
    assert {tail[1].id, tail[2].id}.isdisjoint(recorded)

    resumed = RecordingDDL()
    assert migrations.migrate(resumed) == [tail[1].id, tail[2].id]
    assert resumed.calls == [s.schema_version.name, tail[1].table, tail[2].table]


def test_schema_state_reports_a_step_not_yet_recorded(recorded_steps) -> None:
    last = migrations.steps()[-1]
    _forget([last])

    state = schema_state()
    assert not state.current
    assert state.missing == (last.id,)
