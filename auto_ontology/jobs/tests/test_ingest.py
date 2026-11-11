# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Which sources one ingest run reads, and how a failure is counted."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from auto_ontology.jobs import ingest

SOURCES = [
    {"name": "sales_mysql", "database_name": "sales"},
    {"name": "crm_pg", "database_name": "crm"},
    {"name": "gone", "database_name": "gone"},
]


@pytest.fixture
def ingested(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from auto_ontology.connectors import registry, sources
    from auto_ontology.ingestion_service import ingest as ingest_service

    seen: list[str] = []

    def run_ingest(connector: SimpleNamespace) -> None:
        seen.append(connector.database_name)
        if connector.database_name == "crm":
            raise RuntimeError("connection reset")

    monkeypatch.setattr(sources, "list_sources", lambda: SOURCES)
    monkeypatch.setattr(
        registry,
        "get_connectors",
        lambda: [SimpleNamespace(database_name=name) for name in ("crm", "sales")],
    )
    monkeypatch.setattr(ingest_service, "run_ingest", run_ingest)
    return seen


def test_a_failed_or_unreachable_source_does_not_stop_the_rest(
    ingested: list[str],
) -> None:
    assert ingest.ingest_sources() == (1, 2)
    assert ingested == ["crm", "sales"]


def test_one_source_can_be_ingested_alone(ingested: list[str]) -> None:
    assert ingest.ingest_sources("sales_mysql") == (1, 0)
    assert ingested == ["sales"]


def test_an_unknown_source_is_an_error(ingested: list[str]) -> None:
    with pytest.raises(ValueError, match="no source"):
        ingest.ingest_sources("nope")


def test_a_source_ontology_yaml_names_but_cannot_add_fails_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import contextlib

    from auto_ontology.connectors import sources
    from auto_ontology.hopsworks import config
    from auto_ontology.infra import feature_flags

    monkeypatch.setattr(ingest, "pipeline_lease", contextlib.nullcontext)
    monkeypatch.setattr(config, "load", lambda: SimpleNamespace(sources=()))
    monkeypatch.setattr(feature_flags, "seed_from_config", lambda config: None)
    monkeypatch.setattr(sources, "seed_sources", lambda config: ([], ["sales_mysql"]))
    monkeypatch.setattr(ingest, "ingest_sources", lambda only=None: (0, 0))
    assert ingest.main([]) == 1
