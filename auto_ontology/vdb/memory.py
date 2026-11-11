# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""An in-process vector store with the feature-group store's interface.

For tests and local runs without a Hopsworks cluster: exact cosine search over
a dict, shared per collection name within the process. Nothing persists.
"""

from __future__ import annotations

import threading
from typing import Any, ClassVar

from auto_ontology.vdb.feature_group import PROMOTED, _cosine_distance, _flatten


class MemoryVDB:
    metadata_filter_format = "dict"

    _collections: ClassVar[dict[str, MemoryVDB]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, collection_name: str) -> None:
        self.collection_name = collection_name
        self.rows: dict[str, dict[str, Any]] = {}

    @classmethod
    def collection(
        cls, name: str, *, database_name: str | None = None, reset: bool = False
    ) -> MemoryVDB:
        with cls._lock:
            vdb = cls._collections.setdefault(name, cls(name))
        if database_name and reset:
            vdb.delete_by_database(database_name)
        return vdb

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._collections.clear()

    def create_index(self, **_: Any) -> str:
        return self.collection_name

    def write_to_index(self, records: list, batch_size: int = 500, **_: Any) -> int:
        written = 0
        for record in _flatten(records):
            metadata = dict(record.get("metadata") or {})
            embedding = metadata.pop("embedding", None)
            text = (
                record.get("text") or record.get("content") or metadata.get("content")
            )
            if not embedding or not text or not metadata.get("id"):
                continue
            self.rows[str(metadata["id"])] = {
                "text": text,
                "metadata": metadata,
                "embedding": [float(v) for v in embedding],
            }
            written += 1
        return written

    def run(self, records: list) -> int:
        return self.write_to_index(records)

    def split_changed(
        self, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        ids: list[str] = []
        changed: list[dict[str, Any]] = []
        for row in rows:
            node_id = (row.get("metadata") or {}).get("id")
            text = row.get("text") or row.get("content")
            if not node_id or not text:
                continue
            ids.append(str(node_id))
            existing = self.rows.get(str(node_id))
            if existing is None or existing["text"] != text:
                changed.append(row)
        return changed, ids

    def delete_missing(self, database_name: str, keep: Any, labels: Any = None) -> int:
        kept = set(keep)
        stale = [
            node_id
            for node_id, row in self.rows.items()
            if row["metadata"].get("database_name") == database_name
            and node_id not in kept
            and (not labels or row["metadata"].get("label") in labels)
        ]
        for node_id in stale:
            del self.rows[node_id]
        return len(stale)

    def delete_by_database(self, database_name: str) -> list[str]:
        ids = [
            i
            for i, row in self.rows.items()
            if row["metadata"].get("database_name") == database_name
        ]
        for node_id in ids:
            del self.rows[node_id]
        return ids

    def delete_all(self) -> int:
        count = len(self.rows)
        self.rows.clear()
        return count

    def delete_by_id(self, node_id: str) -> int:
        return 1 if self.rows.pop(node_id, None) is not None else 0

    def _matches(self, metadata: dict[str, Any], where: dict[str, Any] | None) -> bool:
        for key, value in (where or {}).items():
            actual = metadata.get(key)
            if key in PROMOTED and actual is not None:
                actual = str(actual)
            if isinstance(value, list | tuple | set):
                if actual not in {str(v) if key in PROMOTED else v for v in value}:
                    return False
            elif actual != (str(value) if key in PROMOTED else value):
                return False
        return True

    def retrieval(
        self, queries: list, top_k: int = 10, **kwargs: Any
    ) -> list[list[dict]]:
        where = kwargs.get("where")
        results = []
        for query in queries:
            hits = [
                {
                    "text": row["text"],
                    "metadata": row["metadata"],
                    "_distance": _cosine_distance(query, row["embedding"]),
                }
                for row in self.rows.values()
                if self._matches(row["metadata"], where)
            ]
            hits.sort(key=lambda hit: hit["_distance"])
            results.append(hits[:top_k])
        return results

    def close(self) -> None:
        """Nothing to release."""
