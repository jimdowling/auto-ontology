# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The feature-group vector store's contract, against a fake feature group.

The fake stands in for hsfs (no cluster); the ``vector_row`` bookkeeping runs on
the test store and these tests skip without one. What OpenSearch itself does
with the filters and the index is a loadtest's job.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from auto_ontology.vdb import feature_group as fgvdb
from auto_ontology.vdb.feature_group import FeatureGroupVDB, VectorIngestionError

pytestmark = pytest.mark.skipif(
    not os.environ.get("MYSQL_USER"), reason="MYSQL_* not set"
)


class _Clause:
    def __init__(self, *parts: Any) -> None:
        self.parts = parts

    def __and__(self, other: "_Clause") -> "_Clause":
        return _Clause("and", self, other)


class _Feature:
    def __init__(self, name: str) -> None:
        self.name = name

    def __eq__(self, other: object) -> Any:  # type: ignore[override]
        return _Clause("eq", self.name, other)

    def isin(self, values: list[Any]) -> Any:
        return _Clause("in", self.name, tuple(values))


class _Ingestion:
    def __init__(self, statuses: list[str]) -> None:
        self.id = 7
        self.results = [type("R", (), {"status": status})() for status in statuses]


class FakeFeatureGroup:
    def __init__(self) -> None:
        self.features = [
            _Feature(name)
            for name in (
                "id",
                *fgvdb.PROMOTED,
                "is_unique",
                "document_type",
                "text",
                "metadata",
                "embedding",
            )
        ]
        self.rows: dict[str, dict[str, Any]] = {}
        self.statuses = ["UPDATED"]
        self.last_filter: Any = None

    def __getitem__(self, name: str) -> _Feature:
        return _Feature(name)

    def insert(self, frame: Any, write_options: dict[str, Any]) -> None:
        assert write_options["wait_for_online_ingestion"] is True
        for row in frame.to_dict(orient="records"):
            self.rows[row["id"]] = row

    def get_latest_online_ingestion(self) -> _Ingestion:
        return _Ingestion(self.statuses)

    def remove_rows(
        self, frame: Any, storage: str, write_options: dict[str, Any]
    ) -> None:
        assert storage == "online"
        for node_id in frame["id"]:
            self.rows.pop(node_id, None)

    def find_neighbors(
        self, query: list[float], k: int, filter: Any
    ) -> list[tuple[float, list[Any]]]:
        self.last_filter = filter
        return [
            (0.0, [row.get(feature.name) for feature in self.features])
            for row in list(self.rows.values())[:k]
        ]


def _record(
    node_id: str, text: str, vector: list[float], database: str = "sales"
) -> dict[str, Any]:
    return {
        "text": text,
        "document_type": "text",
        "metadata": {
            "id": node_id,
            "label": "Term",
            "name": text,
            "database_name": database,
            "embedding": vector,
        },
    }


@pytest.fixture
def vdb(monkeypatch: pytest.MonkeyPatch) -> FeatureGroupVDB:
    from auto_ontology.dal import schema as s
    from auto_ontology.dal.session import store

    store().query_write(s.vector_row.delete())
    fake = FakeFeatureGroup()
    store_vdb = FeatureGroupVDB(
        collection_name="semantic_layer", feature_group="fg", version=1, dimension=2
    )
    monkeypatch.setattr(store_vdb, "_feature_group", lambda create=True: fake)
    store_vdb.fake = fake  # type: ignore[attr-defined]
    return store_vdb


def test_hits_come_back_in_the_upstream_shape_nearest_first(
    vdb: FeatureGroupVDB,
) -> None:
    vdb.run([[_record("a", "Customer", [1.0, 0.0]), _record("b", "Order", [0.0, 1.0])]])
    hits = vdb.retrieval(
        [[0.0, 1.0]], top_k=2, where={"label": ["Term"], "database_name": "sales"}
    )[0]
    assert [hit["text"] for hit in hits] == ["Order", "Customer"]
    assert hits[0]["_distance"] == pytest.approx(0.0)
    assert hits[1]["_distance"] == pytest.approx(1.0)
    assert hits[0]["metadata"]["label"] == "Term"
    combined = vdb.fake.last_filter  # type: ignore[attr-defined]
    assert combined.parts[0] == "and"
    assert combined.parts[1].parts == ("in", "label", (fgvdb.filter_key("Term"),))
    assert combined.parts[2].parts == ("eq", "database_name", fgvdb.filter_key("sales"))


def test_filtered_columns_are_stored_as_single_token_keys(vdb: FeatureGroupVDB) -> None:
    # The index maps strings to analyzed text and hsfs filters with exact terms, so
    # "Sales Order" could never match as written; a lowercase hex key always does.
    vdb.run([[_record("a", "Sales Order", [1.0, 0.0])]])
    stored = vdb.fake.rows["a"]  # type: ignore[attr-defined]
    assert stored["label"] == fgvdb.filter_key("Term")
    assert stored["name"] == fgvdb.filter_key("Sales Order")
    assert stored["name"].isalnum() and stored["name"] == stored["name"].lower()
    assert json.loads(stored["metadata"])["name"] == "Sales Order"


def test_only_changed_rows_need_embedding(vdb: FeatureGroupVDB) -> None:
    vdb.run([[_record("a", "Customer", [1.0, 0.0])]])
    rows = [
        {"text": "Customer", "metadata": {"id": "a"}},
        {"text": "Order (edited)", "metadata": {"id": "b"}},
    ]
    changed, ids = vdb.split_changed(rows)
    assert [row["metadata"]["id"] for row in changed] == ["b"]
    assert ids == ["a", "b"]


def test_vectors_of_rows_that_are_gone_are_removed(vdb: FeatureGroupVDB) -> None:
    vdb.run([[_record("a", "Customer", [1.0, 0.0]), _record("b", "Order", [0.0, 1.0])]])
    assert vdb.delete_missing("sales", keep=["a"], labels=["Term"]) == 1
    assert set(vdb.fake.rows) == {"a"}  # type: ignore[attr-defined]
    assert vdb.delete_by_database("sales") == ["a"]
    assert vdb.fake.rows == {}  # type: ignore[attr-defined]


def test_a_failed_ingestion_is_not_recorded(vdb: FeatureGroupVDB) -> None:
    vdb.fake.statuses = ["UPDATED", "FAILED"]  # type: ignore[attr-defined]
    with pytest.raises(VectorIngestionError):
        vdb.run([[_record("a", "Customer", [1.0, 0.0])]])
    changed, _ = vdb.split_changed([{"text": "Customer", "metadata": {"id": "a"}}])
    assert len(changed) == 1


def test_a_wrong_dimension_is_refused(vdb: FeatureGroupVDB) -> None:
    with pytest.raises(ValueError, match="dimensions"):
        vdb.run([[_record("a", "Customer", [1.0, 0.0, 0.0])]])


def test_vectors_are_written_as_float32(vdb: FeatureGroupVDB) -> None:
    # hsfs infers array<double> from Python floats, which the array<float>
    # embedding feature refuses; float32 arrays infer array<float>.
    vdb.run([[_record("a", "Customer", [1.0, 0.0])]])
    stored = vdb.fake.rows["a"]["embedding"]  # type: ignore[attr-defined]
    assert str(stored.dtype) == "float32"
    assert stored.tolist() == [1.0, 0.0]


def test_a_row_written_in_an_older_layout_is_rewritten(vdb: FeatureGroupVDB) -> None:
    from auto_ontology.dal import schema as s
    from auto_ontology.dal.session import store

    vdb.run([[_record("a", "Customer", [1.0, 0.0])]])
    # What a row written before keyed filters recorded: the hash of its bare text.
    store().query_write(
        s.vector_row.update()
        .where(s.vector_row.c.id == "a")
        .values(text_hash=fgvdb.text_hash("Customer"))
    )
    changed, _ = vdb.split_changed([{"text": "Customer", "metadata": {"id": "a"}}])
    assert len(changed) == 1
