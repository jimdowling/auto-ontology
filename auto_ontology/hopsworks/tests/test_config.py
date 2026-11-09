# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ontology.yaml parsing against the contract."""

from __future__ import annotations

import copy

import pytest

from auto_ontology.hopsworks.config import ConfigError, parse

DOCUMENT = {
    "schema_version": 1,
    "name": "sales-ontology",
    "app": "sales-ontology",
    "feature_store": None,
    "feature_groups": {
        "data_objects": "sales_ontology_data_objects",
        "semantic": "sales_ontology_semantic",
        "version": 1,
    },
    "embedding": {
        "mode": "local",
        "deployment": "nemotronembed",
        "model": "nvidia/Nemotron-3.5-Embed-1B-BF16",
        "dimension": 2048,
        "request": "v1-prefix",
    },
    "llm": {"mode": "local", "deployment": "nemotronllm", "model": None},
    "sources": [{"name": "sales_mysql", "schemas": ["sales"], "table_regex": None}],
    "jobs": {"ingest": "sales-ontology-ingest", "compile": "sales-ontology-compile"},
    "pii_detection": False,
}


def test_the_contract_example_parses() -> None:
    config = parse(copy.deepcopy(DOCUMENT))
    assert config.semantic_fg == "sales_ontology_semantic"
    assert config.embedding.dimension == 2048
    assert config.sources[0].schemas == ("sales",)
    assert config.jobs["compile"] == "sales-ontology-compile"
    assert config.distinct_value_probing is True


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(schema_version=2), "schema_version"),
        (lambda d: d["llm"].update(mode="platform"), "llm.mode"),
        (lambda d: d["embedding"].update(request="v3"), "embedding.request"),
        (lambda d: d.pop("feature_groups"), "feature_groups"),
    ],
)
def test_a_mismatch_is_a_config_error(change, message: str) -> None:
    document = copy.deepcopy(DOCUMENT)
    change(document)
    with pytest.raises(ConfigError, match=message):
        parse(document)
