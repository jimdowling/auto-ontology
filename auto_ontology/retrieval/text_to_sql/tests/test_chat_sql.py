# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Chat SQL is logged, capped in time, and limited to one read-only query."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from pytest import LogCaptureFixture

from auto_ontology.infra.feature_flags import DEFAULT_SQL_QUERY_TIMEOUT_SECONDS
from auto_ontology.retrieval.text_to_sql import chat_sql
from auto_ontology.retrieval.text_to_sql.chat_sql import (
    _MAX_LOGGED_SQL_CHARS,
    execute_chat_sql,
    log_chat_sql,
    truncate_sql,
)

_LOGGER = "auto_ontology.retrieval.text_to_sql.chat_sql"


@pytest.fixture
def configured_timeout(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Stub the settings read; append to the list to change the stored value."""
    stored = [DEFAULT_SQL_QUERY_TIMEOUT_SECONDS]
    monkeypatch.setattr(chat_sql, "get_sql_query_timeout_seconds", lambda: stored[-1])
    return stored


def test_logs_the_database_and_statement(caplog: LogCaptureFixture) -> None:
    connector = SimpleNamespace(database_name="mydb")

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        log_chat_sql(connector, "SELECT 1")

    messages = [r.getMessage() for r in caplog.records]
    assert "[mydb] Executing chat SQL:\nSELECT 1" in messages


def test_probe_queries_are_labelled(caplog: LogCaptureFixture) -> None:
    connector = SimpleNamespace(database_name="kdc_ca1")

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        log_chat_sql(connector, "SELECT 1", kind="probe SQL")

    assert any("Executing probe SQL:" in r.getMessage() for r in caplog.records)


def test_unknown_database_name_does_not_crash(caplog: LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        log_chat_sql(SimpleNamespace(), "SELECT 1")

    assert "[unknown] Executing chat SQL:\nSELECT 1" in [
        r.getMessage() for r in caplog.records
    ]


def test_long_sql_is_truncated() -> None:
    assert truncate_sql("SELECT 1") == "SELECT 1"

    truncated = truncate_sql("x" * (_MAX_LOGGED_SQL_CHARS + 50))
    assert truncated.startswith("x" * 100)
    assert "[50 more chars]" in truncated


class _Recorder:
    """Connector stub recording how ``execute`` was called."""

    database_name = "kdc_ca1"

    def __init__(self, supports_timeout: bool) -> None:
        self.supports_statement_timeout = supports_timeout
        self.calls: list[tuple[str, dict]] = []

    def execute(self, sql: str, **kwargs: object) -> str:
        self.calls.append((sql, kwargs))
        return "df"


def test_chat_sql_is_capped_at_30_seconds(configured_timeout: list[int]) -> None:
    connector = _Recorder(supports_timeout=True)

    assert execute_chat_sql(connector, "SELECT 1") == "df"
    assert connector.calls == [
        ("SELECT 1", {"timeout_s": DEFAULT_SQL_QUERY_TIMEOUT_SECONDS})
    ]
    assert DEFAULT_SQL_QUERY_TIMEOUT_SECONDS == 30


def test_chat_sql_uses_the_configured_timeout(configured_timeout: list[int]) -> None:
    """Read per statement, so a change in Agent Settings applies to the next one."""
    connector = _Recorder(supports_timeout=True)

    configured_timeout.append(90)
    execute_chat_sql(connector, "SELECT 1")
    configured_timeout.append(5)
    execute_chat_sql(connector, "SELECT 2")

    assert [kwargs for _, kwargs in connector.calls] == [
        {"timeout_s": 90},
        {"timeout_s": 5},
    ]


def test_without_settings_the_default_is_30_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No frontend means no ``configurations`` table; the read must fall back."""

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("relation does not exist")

    monkeypatch.setattr(
        "auto_ontology.infra.feature_flags._read_configuration_row", _boom
    )
    connector = _Recorder(supports_timeout=True)

    execute_chat_sql(connector, "SELECT 1")

    assert connector.calls == [("SELECT 1", {"timeout_s": 30})]


def test_connectors_without_timeout_support_are_called_unchanged() -> None:
    """A connector without a cap must not get an argument it would reject."""
    connector = _Recorder(supports_timeout=False)

    execute_chat_sql(connector, "SELECT 1")

    assert connector.calls == [("SELECT 1", {})]


def test_probe_sql_is_also_capped(configured_timeout: list[int]) -> None:
    connector = _Recorder(supports_timeout=True)

    execute_chat_sql(connector, "SELECT 1", kind="probe SQL")

    assert connector.calls[0][1] == {"timeout_s": DEFAULT_SQL_QUERY_TIMEOUT_SECONDS}


def test_an_explicit_timeout_overrides_the_configured_one(
    configured_timeout: list[int],
) -> None:
    connector = _Recorder(supports_timeout=True)

    execute_chat_sql(connector, "SELECT 1", timeout_s=7)

    assert connector.calls == [("SELECT 1", {"timeout_s": 7})]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "WITH t AS (SELECT a FROM x) SELECT a FROM t",
        "SELECT a FROM x UNION ALL SELECT a FROM y",
        "(SELECT a FROM x)",
    ],
)
def test_a_single_read_only_query_may_run(sql: str) -> None:
    chat_sql.require_read_only(sql, "postgres")


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM x",
        "SELECT 1; DROP TABLE x",
        "WITH gone AS (DELETE FROM x RETURNING *) SELECT * FROM gone",
        "SELECT * INTO copy FROM x",
        "UPDATE x SET a = 1",
        "CREATE TABLE y AS SELECT * FROM x",
        "GRANT ALL ON x TO PUBLIC",
        "SELECT FROM WHERE (",
    ],
)
def test_anything_else_is_refused_before_it_runs(sql: str) -> None:
    ran: list[str] = []
    connector = SimpleNamespace(
        database_name="db", dialect="postgres", execute=ran.append
    )
    with pytest.raises(chat_sql.ReadOnlySQLError):
        execute_chat_sql(connector, sql)
    assert ran == []
