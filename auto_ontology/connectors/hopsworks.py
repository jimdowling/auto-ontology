# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Connectors for Hopsworks data sources.

An ontology source names a Hopsworks data source; its credentials are read
when a connector is built, with the process's Hopsworks identity (the app's
starter, or the member running a job), and never stored. Only data sources
with SHARED credentials are accepted: the ontology serves every member with one
connection, and a PROVIDED-credentials source would serve them all with the
starter's own login.

Supported: SQL data sources of type MySQL, PostgreSQL and ClickHouse,
Snowflake (password or key pair), and Databricks through a Unity Catalog data
source whose ``arguments`` carry the SQL warehouse ``http_path``.
"""

from __future__ import annotations

from typing import Any

from auto_ontology.catalog.table_filter import ALLOW_KEY
from auto_ontology.connectors.connection_string_factory import build_connection_string

SQL_TYPES = {"MYSQL": "mysql", "POSTGRESQL": "postgresql", "CLICKHOUSE": "clickhouse"}


class UnsupportedSourceError(ValueError):
    """The data source cannot back an ontology source."""


def _arguments(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    if isinstance(value, list):
        return {
            str(item.get("name")): str(item.get("value"))
            for item in value
            if isinstance(item, dict)
        }
    if isinstance(value, str):
        pairs = (part.split("=", 1) for part in value.split(",") if "=" in part)
        return {key.strip(): val.strip() for key, val in pairs}
    return {}


def connection_for(data_source: Any) -> dict[str, Any]:
    """The connection form for an hsfs data source object. Raises
    :class:`UnsupportedSourceError` for PROVIDED credentials or an unsupported type."""
    name = getattr(data_source, "name", "?")
    mode = getattr(data_source, "credentials_mode", "SHARED") or "SHARED"
    if str(mode).upper() != "SHARED":
        raise UnsupportedSourceError(
            f"data source {name!r} uses {mode} credentials; ontology sources need SHARED credentials"
        )
    kind = type(data_source).__name__
    if kind == "SqlConnector":
        engine = SQL_TYPES.get(str(data_source.database_type or "").upper())
        if engine is None:
            raise UnsupportedSourceError(
                f"data source {name!r} is a {data_source.database_type} SQL source; "
                f"supported are {', '.join(SQL_TYPES)}"
            )
        return {
            "type": engine,
            "host": data_source.host,
            "port": data_source.port,
            "database": data_source.database,
            "user": data_source.user,
            "password": data_source.password,
        }
    if kind == "SnowflakeConnector":
        return {
            "type": "snowflake",
            "account": data_source.account,
            "warehouse": data_source.warehouse,
            "database": data_source.database,
            "user": data_source.user,
            "password": data_source.password,
            "private_key": data_source.private_key,
            "private_key_passphrase": data_source.passphrase,
        }
    if kind == "UnityCatalogConnector":
        http_path = _arguments(data_source.arguments).get("http_path")
        if not http_path:
            raise UnsupportedSourceError(
                f"Databricks data source {name!r} has no http_path argument naming its SQL warehouse"
            )
        return {
            "type": "databricks",
            "host": data_source.workspace_url,
            "http_path": http_path,
            "password": data_source.access_token,
            "database": data_source.default_catalog,
        }
    raise UnsupportedSourceError(
        f"data source {name!r} is a {kind}, which the ontology cannot read"
    )


def load_data_source(name: str) -> Any:
    from auto_ontology.hopsworks.client import feature_store
    from auto_ontology.hopsworks.config import load

    return feature_store(load().feature_store).get_storage_connector(name)


def connection_string(source: dict[str, Any]) -> str:
    """The connection string for a stored ontology source ``{"data_source", ...}``."""
    return build_connection_string(
        connection_for(load_data_source(source["data_source"]))
    )


def table_filter_settings(source: dict[str, Any]) -> dict[str, Any]:
    """The table filter keys :func:`~auto_ontology.catalog.table_filter.from_connection` reads."""
    regex = source.get("table_regex")
    return {ALLOW_KEY: regex} if regex else {}
