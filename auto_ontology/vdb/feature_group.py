# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Vector store on Hopsworks feature groups with OpenSearch embedding indexes.

One online feature group per collection (``ontology.yaml`` names them), keyed
by the ontology row id, with a dedicated embedding index. The interface is the
one the rest of Auto Ontology already calls: ``run``/``write_to_index`` take
records shaped by :func:`auto_ontology.vdb.records.to_vdb_records`,
``retrieval`` returns ``{"text", "metadata", "_distance"}`` hits with
``_distance`` the cosine distance (``1 - cos``), and the ``delete_*`` methods
remove vectors.

The vector index can only be searched by similarity, so what each feature
group holds is also recorded in the ``vector_row`` table; deletes by database
read their ids from it, and reconciliation compares its text hashes with the
ontology's current text.

Online writes go through Kafka and OnlineFS. :meth:`write_to_index` waits for
the online ingestion and counts a batch as written only when no row FAILED or
was IGNORED; otherwise it records nothing for the batch and raises, so the
next embed run writes it again. Deletes remove vectors from the online store
only: the offline copy, refreshed by the feature group's daily backfill, is a
history nothing in Auto Ontology reads.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
from sqlalchemy import select, text

from auto_ontology.dal import ops
from auto_ontology.dal import schema as s
from auto_ontology.dal.session import store

logger = logging.getLogger(__name__)

#: Metadata keys stored as their own features so searches can filter on them.
PROMOTED = (
    "label",
    "name",
    "database_name",
    "schema_name",
    "term_name",
    "table_id",
    "table_name",
    "source_column",
    "data_type",
    "source_path",
)

#: Seconds to wait for one batch's online ingestion before treating it as failed.
INGESTION_TIMEOUT_S = 600


class VectorIngestionError(RuntimeError):
    """Some rows of a batch did not reach the vector index."""


#: String features searches filter on, stored as :func:`filter_key` values.
KEYED = (*PROMOTED, "document_type")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


#: Changes whenever the stored row layout does, so rows written in an older
#: layout read as changed and the next embed run rewrites them.
ROW_LAYOUT = "keyed-filters"


def row_hash(text: str) -> str:
    """The hash recorded for a written row: its text in the current :data:`ROW_LAYOUT`."""
    return text_hash(f"{ROW_LAYOUT}\n{text}")


def filter_key(value: Any) -> str:
    """The stored form of a :data:`KEYED` value.

    Hopsworks maps string features of an embedding index to analyzed OpenSearch
    ``text``, and hsfs filters them with exact ``term`` queries, so ``"Term"`` or
    ``"Sales Order"`` never match. A lowercase hex digest is a single token that
    the analyzer keeps as it is.
    """
    return text_hash(str(value))[:32]


def _flatten(records: Iterable[Any]) -> Iterable[dict[str, Any]]:
    for record in records or ():
        if isinstance(record, list):
            yield from _flatten(record)
        elif isinstance(record, dict):
            yield record


def _cosine_distance(query: Sequence[float], stored: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(query, stored, strict=False))
    norms = math.sqrt(sum(a * a for a in query)) * math.sqrt(sum(b * b for b in stored))
    return 1.0 - dot / norms if norms else 1.0


def _features(dimension: int) -> list[Any]:
    from hsfs.feature import Feature

    return [
        Feature("id", type="string"),
        *(Feature(name, type="string") for name in PROMOTED),
        Feature("is_unique", type="boolean"),
        Feature("document_type", type="string"),
        Feature("text", type="string"),
        Feature("metadata", type="string"),
        Feature("embedding", type="array<float>"),
    ]


class FeatureGroupVDB:
    """One embedding feature group, addressed as a vector collection."""

    #: ``retrieval`` takes ``where`` as a flat ``{column: value | [values]}`` dict.
    metadata_filter_format = "dict"

    def __init__(
        self,
        *,
        collection_name: str,
        feature_group: str,
        version: int,
        dimension: int,
        feature_store: str | None = None,
        database_name: str | None = None,
        reset: bool = False,
    ) -> None:
        self.collection_name = collection_name
        self.feature_group_name = feature_group
        self.version = version
        self.dimension = dimension
        self.feature_store_name = feature_store
        self.database_name = database_name
        self._fg: Any = None
        if database_name and reset:
            deleted = self.delete_by_database(database_name)
            logger.info(
                "Deleted %d vectors of database %s", len(deleted), database_name
            )

    def _feature_group(self, create: bool = True) -> Any:
        if self._fg is not None:
            return self._fg
        from hsfs.embedding import EmbeddingIndex, SimilarityFunctionType

        from auto_ontology.hopsworks.client import feature_store

        fs = feature_store(self.feature_store_name)
        if not create:
            try:
                self._fg = fs.get_feature_group(self.feature_group_name, self.version)
            except Exception:
                return None
            return self._fg
        index = EmbeddingIndex(index_name=f"{self.feature_group_name}_{self.version}")
        index.add_embedding(
            "embedding",
            self.dimension,
            similarity_function_type=SimilarityFunctionType.COSINE,
        )
        self._fg = fs.get_or_create_feature_group(
            name=self.feature_group_name,
            version=self.version,
            description=f"Ontology vectors: {self.collection_name}",
            primary_key=["id"],
            online_enabled=True,
            embedding_index=index,
            features=_features(self.dimension),
            statistics_config=False,
            offline_backfill_every_hr=24,
        )
        return self._fg

    def create_index(self, **_: Any) -> str:
        self._feature_group()
        return self.collection_name

    def _rows(self, records: Iterable[Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for record in _flatten(records):
            metadata = dict(record.get("metadata") or {})
            embedding = metadata.pop("embedding", None)
            text = (
                record.get("text") or record.get("content") or metadata.get("content")
            )
            node_id = metadata.get("id")
            if not embedding or not text or not node_id:
                continue
            if len(embedding) != self.dimension:
                raise ValueError(
                    f"{self.collection_name}: embedding of {len(embedding)} dimensions, "
                    f"the feature group holds {self.dimension}"
                )
            row = {"id": str(node_id), "text": text}
            for key in PROMOTED:
                value = metadata.get(key)
                row[key] = None if value is None else str(value)
            unique = metadata.get("is_unique")
            row["is_unique"] = None if unique is None else bool(unique)
            row["document_type"] = record.get("document_type")
            row["metadata"] = json.dumps(metadata, default=str)
            # float32: hsfs reads a list of Python floats as array<double>, which the
            # array<float> feature refuses.
            row["embedding"] = np.asarray(embedding, dtype=np.float32)
            rows.append(row)
        return rows

    def _check_ingestion(self, fg: Any) -> None:
        ingestion = fg.get_latest_online_ingestion()
        statuses = {result.status for result in (ingestion.results or [])}
        if statuses & {"FAILED", "IGNORED"}:
            raise VectorIngestionError(
                f"{self.collection_name}: online ingestion {ingestion.id} ended {sorted(statuses)}"
            )

    def write_to_index(self, records: list, batch_size: int = 500, **_: Any) -> int:
        """Upsert the records' vectors by id; returns how many were written.

        Raises :class:`VectorIngestionError` when a batch's online ingestion
        reports failed or ignored rows; the batches before it stay written.
        """
        import pandas as pd

        rows = self._rows(records)
        if not rows:
            return 0
        fg = self._feature_group()
        written = 0
        for batch in ops.chunks(rows, batch_size):
            keyed = [
                {
                    **row,
                    **{
                        key: filter_key(row[key])
                        for key in KEYED
                        if row.get(key) is not None
                    },
                }
                for row in batch
            ]
            fg.insert(
                pd.DataFrame(keyed),
                write_options={
                    "wait_for_online_ingestion": True,
                    "online_ingestion_options": {"timeout": INGESTION_TIMEOUT_S},
                    "start_offline_materialization": False,
                },
            )
            self._check_ingestion(fg)
            ops.upsert(
                s.vector_row,
                [
                    {
                        "collection": self.collection_name,
                        "id": row["id"],
                        "database_name": row["database_name"],
                        "label": row["label"],
                        "text_hash": row_hash(row["text"]),
                    }
                    for row in batch
                ],
                key=["collection", "id"],
                set_=lambda new: {
                    "database_name": new.database_name,
                    "label": new.label,
                    "text_hash": new.text_hash,
                    "written_at": text("CURRENT_TIMESTAMP(6)"),
                },
            )
            written += len(batch)
        logger.info("Wrote %d vectors to %s", written, self.collection_name)
        return written

    def _remove(self, ids: list[str]) -> int:
        import pandas as pd

        if not ids:
            return 0
        fg = self._feature_group(create=False)
        if fg is not None:
            for batch in ops.chunks(ids):
                fg.remove_rows(
                    pd.DataFrame({"id": batch}),
                    storage="online",
                    write_options={"wait_for_online_ingestion": True},
                )
        for batch in ops.chunks(ids):
            store().query_write(
                s.vector_row.delete().where(
                    s.vector_row.c.collection == self.collection_name,
                    s.vector_row.c.id.in_(batch),
                )
            )
        return len(ids)

    def _ids(self, *conditions: Any) -> list[str]:
        return [
            row["id"]
            for row in store().query_read(
                select(s.vector_row.c.id).where(
                    s.vector_row.c.collection == self.collection_name, *conditions
                )
            )
        ]

    def split_changed(
        self, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """``(rows to embed, ids of every row)`` for not-yet-embedded rows.

        A row is unchanged when ``vector_row`` holds its id with the hash of its
        current text; those are left out, so only new or edited rows reach the
        embedding endpoint. Rows without an id or text are dropped.
        """
        ids: list[str] = []
        texts: dict[str, str] = {}
        for row in rows:
            node_id = (row.get("metadata") or {}).get("id")
            text = row.get("text") or row.get("content")
            if node_id and text:
                ids.append(str(node_id))
                texts[str(node_id)] = text
        stored: dict[str, str] = {}
        for batch in ops.chunks(ids):
            for hit in store().query_read(
                select(s.vector_row.c.id, s.vector_row.c.text_hash).where(
                    s.vector_row.c.collection == self.collection_name,
                    s.vector_row.c.id.in_(batch),
                )
            ):
                stored[hit["id"]] = hit["text_hash"]
        changed = [
            row
            for row in rows
            if (node_id := str((row.get("metadata") or {}).get("id") or "")) in texts
            and stored.get(node_id) != row_hash(texts[node_id])
        ]
        return changed, ids

    def delete_missing(
        self,
        database_name: str,
        keep: Iterable[str],
        labels: Sequence[str] | None = None,
    ) -> int:
        """Remove the database's vectors whose ids are not in ``keep``, only of
        ``labels`` when given; returns how many."""
        kept = set(keep)
        conditions = [s.vector_row.c.database_name == database_name]
        if labels:
            conditions.append(s.vector_row.c.label.in_(list(labels)))
        stale = [node_id for node_id in self._ids(*conditions) if node_id not in kept]
        return self._remove(stale)

    def delete_by_database(self, database_name: str) -> list[str]:
        ids = self._ids(s.vector_row.c.database_name == database_name)
        self._remove(ids)
        return ids

    def delete_all(self) -> int:
        return self._remove(self._ids())

    def delete_by_id(self, node_id: str) -> int:
        return self._remove(self._ids(s.vector_row.c.id == node_id))

    def _filter(self, fg: Any, where: dict[str, Any] | None) -> Any:
        condition = None
        for key, value in (where or {}).items():
            feature = fg[key]
            values = list(value) if isinstance(value, list | tuple | set) else [value]
            if key in KEYED:
                values = [filter_key(v) for v in values]
            if isinstance(value, list | tuple | set):
                clause = feature.isin(values)
            else:
                clause = feature == values[0]
            condition = clause if condition is None else condition & clause
        return condition

    def retrieval(
        self, queries: list, top_k: int = 10, **kwargs: Any
    ) -> list[list[dict]]:
        """k-NN search for each query vector, nearest first.

        ``kwargs["where"]`` restricts the search to rows whose promoted columns
        match (a list means "any of"). Returns an empty list per query when the
        feature group does not exist yet or the search fails.
        """
        fg = self._feature_group(create=False)
        if fg is None:
            return [[] for _ in queries]
        names = [feature.name for feature in fg.features]
        condition = self._filter(fg, kwargs.get("where"))
        results: list[list[dict]] = []
        for query in queries:
            try:
                hits = fg.find_neighbors(list(query), k=top_k, filter=condition)
            except Exception:
                logger.exception("Vector search on %s failed", self.collection_name)
                return [[] for _ in queries]
            converted = []
            for _score, values in hits:
                row = dict(zip(names, values, strict=False))
                metadata = json.loads(row.get("metadata") or "{}")
                stored = row.get("embedding")
                converted.append(
                    {
                        "text": row.get("text"),
                        "metadata": metadata,
                        "_distance": _cosine_distance(
                            query, () if stored is None else stored
                        ),
                    }
                )
            converted.sort(key=lambda hit: hit["_distance"])
            results.append(converted[:top_k])
        return results

    def run(self, records: list) -> int:
        self.create_index()
        return self.write_to_index(records)

    def close(self) -> None:
        """Nothing to release: the hopsworks client is process-wide."""
