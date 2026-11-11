# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Vector collections: the data layer and the semantic layer.

On Hopsworks each collection is an embedding feature group named in
``ontology.yaml``. Setting ``AUTO_ONTOLOGY_VDB=memory`` swaps in an in-process
store, for tests and local runs without a cluster.
"""

from __future__ import annotations

import os
from typing import Any

DATA_VDB_COLLECTION: str = "data_objects_layer"
SEMANTIC_VDB_COLLECTION: str = "semantic_layer"


def get_vdb(
    *,
    database_name: str | None = None,
    collection_name: str = DATA_VDB_COLLECTION,
    reset: bool = False,
) -> Any:
    """The vector store for ``collection_name``.

    With ``database_name`` and ``reset``, that database's vectors are deleted
    first, before an ingest rewrites them.
    """
    if os.environ.get("AUTO_ONTOLOGY_VDB") == "memory":
        from auto_ontology.vdb.memory import MemoryVDB

        return MemoryVDB.collection(
            collection_name, database_name=database_name, reset=reset
        )

    from auto_ontology.hopsworks.config import load
    from auto_ontology.vdb.feature_group import FeatureGroupVDB

    config = load()
    feature_group = (
        config.data_objects_fg
        if collection_name == DATA_VDB_COLLECTION
        else config.semantic_fg
    )
    return FeatureGroupVDB(
        collection_name=collection_name,
        feature_group=feature_group,
        version=config.fg_version,
        dimension=config.embedding.dimension,
        feature_store=config.feature_store,
        database_name=database_name,
        reset=reset,
    )


def get_data_vdb(*, database_name: str | None = None, reset: bool = False) -> Any:
    """The data-layer collection (tables and columns)."""
    return get_vdb(database_name=database_name, reset=reset)


def get_semantic_vdb(*, database_name: str | None = None, reset: bool = False) -> Any:
    """The semantic-layer collection (terms, attributes, analyses)."""
    return get_vdb(
        database_name=database_name,
        collection_name=SEMANTIC_VDB_COLLECTION,
        reset=reset,
    )
