# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Adding, removing and seeding sources, on the test store."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("MYSQL_USER"), reason="MYSQL_* not set"
)

#: data source name -> the database its connector reports.
DATABASES = {"sales_mysql": "sales", "sales_copy": "sales", "crm_pg": "crm"}


@pytest.fixture(autouse=True)
def _connectors(monkeypatch: pytest.MonkeyPatch) -> None:
    from auto_ontology.connectors import sources
    from auto_ontology.dal import schema as s
    from auto_ontology.dal.session import store

    store().query_write(s.catalog_database.delete())
    monkeypatch.setattr(
        sources.hopsworks, "connection_string", lambda source: source["data_source"]
    )
    monkeypatch.setattr(
        sources,
        "create_connector",
        lambda name: SimpleNamespace(database_name=DATABASES[name], close=lambda: None),
    )


def test_a_source_is_filed_under_its_connectors_database() -> None:
    from auto_ontology.connectors import sources

    added = sources.add_source("sales_mysql", ["public"], "^fact_")
    assert added == {
        "name": "sales_mysql",
        "schemas": ["public"],
        "table_regex": "^fact_",
        "database_name": "sales",
    }
    assert sources.list_sources() == [added]


def test_adding_a_source_again_changes_its_filters() -> None:
    from auto_ontology.connectors import sources

    sources.add_source("sales_mysql")
    sources.add_source("sales_mysql", table_regex="^dim_")
    assert [source["table_regex"] for source in sources.list_sources()] == ["^dim_"]


def test_two_sources_may_not_read_one_database() -> None:
    from auto_ontology.connectors import sources

    sources.add_source("sales_mysql")
    with pytest.raises(ValueError, match="already reads"):
        sources.add_source("sales_copy")


def test_removing_a_source_names_the_database_to_reset() -> None:
    from auto_ontology.connectors import sources

    sources.add_source("crm_pg")
    assert sources.remove_source("crm_pg") == "crm"
    assert sources.list_sources() == []
    assert sources.remove_source("crm_pg") is None


def test_ontology_yaml_seeds_only_an_empty_store() -> None:
    from auto_ontology.connectors import sources
    from auto_ontology.hopsworks.config import Source

    config = SimpleNamespace(
        sources=(
            Source(name="sales_mysql", schemas=(), table_regex=None),
            Source(name="missing", schemas=(), table_regex=None),
        )
    )
    assert sources.seed_sources(config) == (["sales_mysql"], ["missing"])
    sources.remove_source("sales_mysql")
    sources.add_source("crm_pg")
    assert sources.seed_sources(config) == ([], [])
    assert [source["name"] for source in sources.list_sources()] == ["crm_pg"]
