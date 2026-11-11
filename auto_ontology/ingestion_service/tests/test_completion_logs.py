# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The "finished successfully" lines must mean it, and only when it did.

These logs exist to answer one operational question from a pod log: did the
ingest actually complete? That is only worth anything if the line cannot
appear after a failure.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from auto_ontology.vdb.memory import MemoryVDB


class _Connector:
    def __init__(self, name: str) -> None:
        self.database_name = name


def _messages(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(record.getMessage() for record in caplog.records)


def _stub_rules(monkeypatch: pytest.MonkeyPatch, rules: Any = None) -> list[bool]:
    """Neutralise the rule replay, and report whether it ran.

    Stubbed like the compilation itself: it reads the rules out of Postgres,
    which these tests have no database for, and it is each caller's decision
    to replay them that is under test here rather than the rules' own
    behaviour. The returned list has an entry per call, so "the rules ran" and
    "the rules did not" are both checkable.
    """
    import auto_ontology.ingestion_service.rules as mod

    ran: list[bool] = []

    def _default() -> tuple[int, int]:
        ran.append(True)
        return 0, 0

    monkeypatch.setattr(mod, "reapply_rules", rules or _default)
    return ran


# --------------------------------------------------------------------------
# run_ingest
# --------------------------------------------------------------------------


@pytest.fixture
def _stub_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise everything run_ingest touches except the logging."""
    import auto_ontology.ingestion_service.ingest as mod

    monkeypatch.setattr(mod, "get_embed_params", lambda: {})
    monkeypatch.setattr(mod, "ingest_catalog", lambda c: ([1, 2, 3], [1, 2]))
    monkeypatch.setattr(mod, "is_pii_detection_enabled", lambda: True)
    monkeypatch.setattr(mod, "detect_and_tag_pii", lambda columns: None)
    monkeypatch.setattr(mod, "run_pii_propagation", lambda label: None)
    monkeypatch.setattr(mod, "CatalogEmbeddingRowsOp", lambda **kw: lambda pair: [])
    monkeypatch.setattr(mod, "get_data_vdb", lambda: MemoryVDB.collection("data"))
    monkeypatch.setattr(
        mod, "batch_embed_chunks", lambda rows, params, label="": iter(())
    )


def test_run_ingest_logs_success_with_counts(
    _stub_ingest: None, caplog: pytest.LogCaptureFixture
) -> None:
    from auto_ontology.ingestion_service.ingest import run_ingest

    with caplog.at_level(logging.INFO):
        run_ingest(_Connector("pagila"))

    text = _messages(caplog)
    assert "Data ingestion started for database pagila" in text
    assert "Data ingestion finished successfully for database pagila" in text
    # The counts come from the catalog frames, not from the embed step.
    assert "3 table(s), 2 column(s)" in text


def test_run_ingest_logs_the_empty_embed_case(
    _stub_ingest: None, caplog: pytest.LogCaptureFixture
) -> None:
    """An empty embed result used to log nothing at all."""
    from auto_ontology.ingestion_service.ingest import run_ingest

    with caplog.at_level(logging.INFO):
        run_ingest(_Connector("pagila"))

    assert "No changed rows embedded for database pagila" in _messages(caplog)


def test_run_ingest_logs_no_success_when_extraction_raises(
    _stub_ingest: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import auto_ontology.ingestion_service.ingest as mod

    def _boom(connector: Any) -> Any:
        raise RuntimeError("catalog extraction failed")

    monkeypatch.setattr(mod, "ingest_catalog", _boom)

    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError):
        mod.run_ingest(_Connector("pagila"))

    assert "finished successfully" not in _messages(caplog)


def test_run_ingest_tags_persisted_columns_before_embedding(
    _stub_ingest: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import auto_ontology.ingestion_service.ingest as mod

    order: list[str] = []

    def ingest(_connector: Any) -> tuple[list[int], list[int]]:
        order.append("catalog")
        return [1], [2]

    def detect(_columns: Any) -> None:
        order.append("pii")

    def embedding_rows(**_kwargs: Any) -> Any:
        def build(pair: Any) -> Any:
            order.append("embedding")
            return []

        return build

    def propagate(_label: str) -> None:
        order.append("propagate")

    monkeypatch.setattr(mod, "ingest_catalog", ingest)
    monkeypatch.setattr(mod, "detect_and_tag_pii", detect)
    monkeypatch.setattr(mod, "run_pii_propagation", propagate)
    monkeypatch.setattr(mod, "CatalogEmbeddingRowsOp", embedding_rows)

    mod.run_ingest(_Connector("pagila"))

    assert order == ["catalog", "pii", "propagate", "embedding"]


def test_detection_failure_still_propagates_pii_to_attributes(
    _stub_ingest: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import auto_ontology.ingestion_service.ingest as mod

    propagated: list[str] = []

    def fail(_columns: Any) -> None:
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(mod, "detect_and_tag_pii", fail)
    monkeypatch.setattr(mod, "run_pii_propagation", propagated.append)

    mod.run_ingest(_Connector("pagila"))

    assert propagated == ["pagila"]


def test_propagation_failure_is_contained(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import auto_ontology.ingestion_service.pii as pii_mod

    def boom() -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(pii_mod, "propagate_pii_to_attributes", boom)

    with caplog.at_level(logging.INFO):
        pii_mod.run_pii_propagation("ingest")

    assert "could not propagate PII tags to attributes" in _messages(caplog)


def test_run_ingest_skips_pii_when_disabled(
    _stub_ingest: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import auto_ontology.ingestion_service.ingest as mod

    pii_runs: list[str] = []
    monkeypatch.setattr(mod, "is_pii_detection_enabled", lambda: False)
    monkeypatch.setattr(
        mod, "detect_and_tag_pii", lambda _columns: pii_runs.append("detect")
    )
    monkeypatch.setattr(
        mod, "run_pii_propagation", lambda _label: pii_runs.append("propagate")
    )

    with caplog.at_level(logging.INFO):
        mod.run_ingest(_Connector("pagila"))

    assert pii_runs == []
    assert "PII detection skipped for database pagila" in _messages(caplog)
    assert "Data ingestion finished successfully for database pagila" in _messages(
        caplog
    )


def test_pii_failure_does_not_fail_catalog_ingestion(
    _stub_ingest: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import auto_ontology.ingestion_service.ingest as mod

    def fail(_columns: Any) -> None:
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(mod, "detect_and_tag_pii", fail)

    with caplog.at_level(logging.INFO):
        mod.run_ingest(_Connector("pagila"))

    text = _messages(caplog)
    assert "PII detection failed for database pagila" in text
    assert "Unprocessed columns will be retried on the next ingest" in text
    assert "Data ingestion finished successfully for database pagila" in text
