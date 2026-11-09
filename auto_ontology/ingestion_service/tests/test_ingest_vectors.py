# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Ingest embeds only what changed, and a failed embed loses no vector.

The previous vectors stay until a row's new text has embedded; vectors of
tables and columns that are gone are removed once the embed step finished.
"""

from __future__ import annotations

from typing import Any, Iterator

import pandas as pd
import pytest

from auto_ontology.vdb.memory import MemoryVDB


class _Connector:
    database_name = "pagila"


def _row(node_id: str, text: str) -> dict[str, Any]:
    return {
        "text": text,
        "path": f"auto_ontology:{node_id}",
        "page_number": -1,
        "metadata": {
            "id": node_id,
            "label": "Table",
            "name": node_id,
            "source_path": f"auto_ontology:{node_id}",
            "database_name": "pagila",
            "content_metadata": {"id": node_id},
        },
    }


@pytest.fixture
def ingest(monkeypatch: pytest.MonkeyPatch) -> Any:
    """``ingest(rows, fail=())`` runs one ingest whose catalog yields ``rows``;
    rows named in ``fail`` come back from the embedder without a vector.
    Returns the ids sent to the embedder."""
    import auto_ontology.ingestion_service.ingest as mod

    MemoryVDB.clear()
    vdb = MemoryVDB.collection("data")
    monkeypatch.setattr(mod, "get_embed_params", lambda: {})
    monkeypatch.setattr(mod, "ingest_catalog", lambda c: ([1], [1]))
    monkeypatch.setattr(mod, "is_pii_detection_enabled", lambda: False)
    monkeypatch.setattr(mod, "get_data_vdb", lambda: vdb)

    def run(rows: list[dict[str, Any]], fail: tuple[str, ...] = ()) -> list[str]:
        sent: list[str] = []

        def embed(chunk: list[dict], params: Any, label: str = "") -> Iterator[Any]:
            out = []
            for row in chunk:
                sent.append(row["metadata"]["id"])
                if row["metadata"]["id"] not in fail:
                    row = {**row, "metadata": {**row["metadata"], "embedding": [0.1]}}
                out.append(row)
            yield pd.DataFrame(out)

        monkeypatch.setattr(
            mod, "CatalogEmbeddingRowsOp", lambda **kw: lambda pair: rows
        )
        monkeypatch.setattr(mod, "batch_embed_chunks", embed)
        mod.run_ingest(_Connector())
        return sent

    run.vdb = vdb
    return run


def test_an_unchanged_catalog_embeds_nothing(ingest: Any) -> None:
    rows = [_row("a", "table a"), _row("b", "table b")]
    assert ingest(rows) == ["a", "b"]
    assert ingest(rows) == []


def test_only_changed_text_is_embedded_again(ingest: Any) -> None:
    ingest([_row("a", "table a"), _row("b", "table b")])
    assert ingest([_row("a", "table a"), _row("b", "table b, renamed")]) == ["b"]
    assert ingest.vdb.rows["b"]["text"] == "table b, renamed"


def test_a_failed_embed_keeps_the_old_vector_and_retries(ingest: Any) -> None:
    ingest([_row("a", "table a")])
    assert ingest([_row("a", "table a v2")], fail=("a",)) == ["a"]
    assert ingest.vdb.rows["a"]["text"] == "table a"
    assert ingest([_row("a", "table a v2")]) == ["a"]
    assert ingest.vdb.rows["a"]["text"] == "table a v2"


def test_a_dropped_table_loses_its_vector(ingest: Any) -> None:
    ingest([_row("a", "table a"), _row("b", "table b")])
    ingest([_row("a", "table a")])
    assert set(ingest.vdb.rows) == {"a"}
