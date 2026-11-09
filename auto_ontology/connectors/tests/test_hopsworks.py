# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Hopsworks data sources to connector connection forms."""

from __future__ import annotations

import pytest

from auto_ontology.connectors.connection_string_factory import build_connection_string
from auto_ontology.connectors.hopsworks import (
    UnsupportedSourceError,
    connection_for,
    table_filter_settings,
)


class SqlConnector:
    def __init__(self, **values: object) -> None:
        self.name = "sales_mysql"
        self.credentials_mode = "SHARED"
        self.__dict__.update(values)


class SnowflakeConnector(SqlConnector):
    pass


class UnityCatalogConnector(SqlConnector):
    pass


class RedshiftConnector(SqlConnector):
    pass


def test_a_mysql_source_becomes_a_mysql_connection_string() -> None:
    source = SqlConnector(
        database_type="MYSQL",
        host="db.local",
        port=3306,
        database="sales",
        user="u",
        password="p@ss",
    )
    assert (
        build_connection_string(connection_for(source))
        == "mysql://u:p%40ss@db.local:3306/sales"
    )


def test_snowflake_keeps_its_key_pair() -> None:
    source = SnowflakeConnector(
        account="acme-1",
        warehouse="wh",
        database="DB",
        user="svc",
        password=None,
        private_key="-----BEGIN PRIVATE KEY-----\nAAA\n-----END PRIVATE KEY-----",
        passphrase=None,
    )
    assert build_connection_string(connection_for(source)).startswith(
        "snowflake://svc@acme-1?"
    )


def test_databricks_needs_the_warehouse_http_path() -> None:
    source = UnityCatalogConnector(
        workspace_url="https://dbc.cloud.databricks.com",
        access_token="tok",
        default_catalog="main",
        arguments=[{"name": "http_path", "value": "/sql/1.0/warehouses/abc"}],
    )
    assert build_connection_string(connection_for(source)).startswith(
        "databricks://token:tok@dbc.cloud.databricks.com/main?http_path="
    )
    source.arguments = []
    with pytest.raises(UnsupportedSourceError, match="http_path"):
        connection_for(source)


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (SqlConnector(database_type="MYSQL", credentials_mode="PROVIDED"), "SHARED"),
        (SqlConnector(database_type="ORACLE"), "ORACLE"),
        (RedshiftConnector(), "RedshiftConnector"),
    ],
)
def test_other_sources_are_refused(source: object, reason: str) -> None:
    with pytest.raises(UnsupportedSourceError, match=reason):
        connection_for(source)


def test_the_table_regex_becomes_an_allow_filter() -> None:
    assert table_filter_settings({"table_regex": "^fact_"}) == {
        "table_allow_regex": "^fact_"
    }
    assert table_filter_settings({"table_regex": None}) == {}
