# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Incremental re-ingest: what changes in the catalog when the source changes.

``update_diff_from_existing_schema`` decides which tables and columns are added,
dropped and updated on every scheduled re-ingest, so a wrong answer either loses
catalog entries users were querying or leaves ghosts pointing at columns that no
longer exist. The end-to-end fixture ingest exercises only the *empty database*
case, where diffing has nothing to do — and re-ingest is where the bugs were.

Each test owns a throwaway MySQL source database on the store's own server, so
it can add and drop tables without disturbing anything else. The MySQL
connector reads one schema, the connection's database, so that is the one
schema every catalog here has. Skips when the store is not configured.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text

from auto_ontology.catalog.tests import catalog_inspector as catalog
from auto_ontology.infra.mysql import mysql_url, store_configured


@pytest.fixture(scope="module", autouse=True)
def require_store() -> None:
    if not store_configured():
        pytest.skip("MYSQL_* not set (needed for the store and the source database)")


def _dsn(database: str) -> str:
    """The MySQL connector's form of the store's server, for *database*."""
    url = mysql_url(database).set(drivername="mysql", query={})
    return url.render_as_string(hide_password=False)


def _mutate(database_name: str, *statements: str) -> None:
    engine = create_engine(mysql_url(database_name))
    try:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
    finally:
        engine.dispose()


@pytest.fixture
def source_db() -> Iterator[str]:
    """A throwaway source database this test may freely mutate."""
    name = f"difftest_{uuid.uuid4().hex[:12]}"
    server = create_engine(mysql_url().set(database=""))
    with server.begin() as connection:
        connection.execute(text(f"CREATE DATABASE `{name}`"))
    _mutate(
        name,
        "CREATE TABLE customer ("
        " customer_id integer PRIMARY KEY,"
        " name varchar(100),"
        " email varchar(200))",
        "CREATE TABLE orders ("
        " order_id integer PRIMARY KEY,"
        " customer_id integer,"
        " total numeric(10,2),"
        " FOREIGN KEY (customer_id) REFERENCES customer(customer_id))",
        "INSERT INTO customer VALUES (1, 'ada', 'a@b.c')",
        "INSERT INTO orders VALUES (1, 1, 9.99)",
    )

    yield name

    catalog.wipe(name)
    with server.begin() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS `{name}`"))
    server.dispose()


def _ingest(database_name: str, *, deny: str | None = None) -> None:
    from auto_ontology.catalog import ingest_catalog
    from auto_ontology.catalog.table_filter import from_connection
    from auto_ontology.connectors.registry import create_connector

    connector = create_connector(
        _dsn(database_name),
        table_filter=from_connection({"table_deny_regex": deny} if deny else None),
    )
    try:
        ingest_catalog(connector)
    finally:
        connector.close()


# ---------------------------------------------------------------------------


def test_first_ingest_creates_the_catalog(source_db: str) -> None:
    _ingest(source_db)
    assert catalog.tables(source_db) == {"customer", "orders"}
    assert catalog.columns(source_db, "customer") == {
        "customer_id",
        "name",
        "email",
    }


def test_reingest_without_changes_is_a_no_op(source_db: str) -> None:
    """The scheduler re-ingests every 24h; an unchanged source must not churn.

    Compared on counts, not names: a duplicate-creating bug keeps every name
    and simply doubles the catalog.
    """
    _ingest(source_db)
    before = catalog.entity_counts(source_db)

    _ingest(source_db)
    after = catalog.entity_counts(source_db)

    assert after == before, f"re-ingest changed the catalog: {before} -> {after}"


def test_added_table_appears_with_its_columns(source_db: str) -> None:
    _ingest(source_db)
    _mutate(
        source_db,
        "CREATE TABLE invoice (invoice_id integer PRIMARY KEY, amount numeric)",
    )
    _ingest(source_db)

    assert "invoice" in catalog.tables(source_db)
    assert catalog.columns(source_db, "invoice") == {"invoice_id", "amount"}


def test_dropped_table_is_removed(source_db: str) -> None:
    """A ghost table is worse than a missing one: it is offered to the SQL
    generator, which then writes queries against a relation that is gone."""
    _ingest(source_db)
    _mutate(source_db, "DROP TABLE orders")
    _ingest(source_db)

    assert catalog.tables(source_db) == {"customer"}


def test_newly_denied_table_is_removed_from_the_catalog(source_db: str) -> None:
    """Adding a denylist must evict what it excludes, not just stop adding it.

    The operator's reason for excluding a table is that querying it fails, so
    leaving the already-ingested copy behind would keep retrieval offering it
    and change nothing they could observe.
    """
    _ingest(source_db)
    assert catalog.tables(source_db) == {"customer", "orders"}

    _ingest(source_db, deny="^orders$")

    assert catalog.tables(source_db) == {"customer"}
    assert catalog.columns(source_db, "orders") == set()


def test_dropped_table_takes_its_columns_with_it(source_db: str) -> None:
    _ingest(source_db)
    _mutate(source_db, "DROP TABLE orders")
    _ingest(source_db)

    assert catalog.columns(source_db, "orders") == set()


def test_added_column_appears(source_db: str) -> None:
    _ingest(source_db)
    _mutate(source_db, "ALTER TABLE customer ADD COLUMN phone varchar(40)")
    _ingest(source_db)

    assert "phone" in catalog.columns(source_db, "customer")


def test_dropped_column_is_removed(source_db: str) -> None:
    _ingest(source_db)
    _mutate(source_db, "ALTER TABLE customer DROP COLUMN email")
    _ingest(source_db)

    assert catalog.columns(source_db, "customer") == {"customer_id", "name"}


def test_renamed_column_is_add_plus_drop(source_db: str) -> None:
    """Rename is indistinguishable from drop+add at the catalog level.

    Worth pinning: it means any curation attached to the old column — a
    description, a ColumnAttribute — does not follow the rename.
    """
    _ingest(source_db)
    _mutate(source_db, "ALTER TABLE customer RENAME COLUMN email TO contact")
    _ingest(source_db)

    names = catalog.columns(source_db, "customer")
    assert "contact" in names
    assert "email" not in names


def test_changed_column_type_is_updated_in_place(source_db: str) -> None:
    """The column keeps its identity; only data_type changes."""
    _ingest(source_db)
    before_id = catalog.column_property(source_db, "customer", "name", "id")
    assert (
        catalog.column_property(source_db, "customer", "name", "data_type") == "varchar"
    )

    _mutate(source_db, "ALTER TABLE customer MODIFY COLUMN name text")
    _ingest(source_db)

    assert catalog.column_property(source_db, "customer", "name", "data_type") == "text"
    assert catalog.column_property(source_db, "customer", "name", "id") == before_id, (
        "the column was recreated rather than updated; anything referencing its "
        "id would now dangle"
    )


def test_added_then_dropped_table_leaves_no_trace(source_db: str) -> None:
    _ingest(source_db)
    baseline = catalog.entity_counts(source_db)

    _mutate(source_db, "CREATE TABLE temp_thing (id integer PRIMARY KEY)")
    _ingest(source_db)
    assert "temp_thing" in catalog.tables(source_db)

    _mutate(source_db, "DROP TABLE temp_thing")
    _ingest(source_db)

    assert "temp_thing" not in catalog.tables(source_db)
    assert catalog.entity_counts(source_db) == baseline


def test_foreign_key_survives_reingest(source_db: str) -> None:
    _ingest(source_db)
    _ingest(source_db)

    assert catalog.foreign_keys(source_db) == {("customer_id", "customer_id")}
