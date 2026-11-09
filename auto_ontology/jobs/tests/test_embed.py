# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Reconciling the semantic vectors with the ontology's rows."""

from __future__ import annotations

from typing import Any, Iterator

import pytest

from auto_ontology.jobs import embed
from auto_ontology.vdb.memory import MemoryVDB


def _row(node_id: str, text: str) -> dict[str, Any]:
    return {
        "text": text,
        "metadata": {"id": node_id, "label": "Term", "database_name": "sales"},
    }


@pytest.fixture
def reconcile(monkeypatch: pytest.MonkeyPatch) -> Any:
    """``reconcile(rows, fail=())`` reconciles database ``sales`` holding
    ``rows``; ids in ``fail`` come back from the embedder without a vector."""
    MemoryVDB.clear()
    vdb = MemoryVDB.collection("semantic")
    monkeypatch.setattr(embed, "get_semantic_vdb", lambda: vdb)
    monkeypatch.setattr(embed, "get_embed_params", lambda: {})

    def run(rows: list[dict[str, Any]], fail: tuple[str, ...] = ()) -> Any:
        def chunks(changed: list, params: Any, label: str = "") -> Iterator[list]:
            yield [
                row
                if row["metadata"]["id"] in fail
                else {**row, "metadata": {**row["metadata"], "embedding": [0.5]}}
                for row in changed
            ]

        monkeypatch.setattr(embed, "semantic_rows", lambda database: rows)
        monkeypatch.setattr(embed, "batch_embed_chunks", chunks)
        return embed.reconcile_database("sales")

    run.vdb = vdb
    return run


def test_new_rows_are_written_and_gone_rows_removed(reconcile: Any) -> None:
    assert reconcile([_row("t1", "revenue"), _row("t2", "churn")]) == (2, 0)
    assert reconcile([_row("t1", "revenue")]) == (0, 1)
    assert set(reconcile.vdb.rows) == {"t1"}


def test_a_row_that_did_not_embed_fails_the_run_and_keeps_its_vector(
    reconcile: Any,
) -> None:
    reconcile([_row("t1", "revenue")])
    with pytest.raises(embed.UnembeddedRowsError, match="1 of 1"):
        reconcile([_row("t1", "net revenue")], fail=("t1",))
    assert reconcile.vdb.rows["t1"]["text"] == "revenue"
