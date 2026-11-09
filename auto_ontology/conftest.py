# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Test session setup for everything that touches the store.

When ``MYSQL_USER`` and ``MYSQL_DB`` are set (see dev_tools/ndb/docker-compose.yml
for a local RonDB-compatible cluster), the database is created if missing and
its tables are dropped and rebuilt through the migration runner once per test
session, so every run starts from the schema the code declares. Without them,
store tests skip.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _store_schema() -> None:
    from auto_ontology.infra.mysql import store_configured

    if not store_configured():
        yield
        return
    from sqlalchemy import create_engine, text

    from auto_ontology.dal import migrations
    from auto_ontology.dal import schema as s
    from auto_ontology.dal.session import dispose_engine, get_engine
    from auto_ontology.infra.mysql import mysql_url

    server = create_engine(mysql_url().set(database=""))
    with server.begin() as connection:
        connection.execute(
            text(f"CREATE DATABASE IF NOT EXISTS `{os.environ['MYSQL_DB']}`")
        )
    server.dispose()
    s.METADATA.drop_all(get_engine())
    migrations.migrate(migrations.DirectDDL())
    yield
    dispose_engine()
