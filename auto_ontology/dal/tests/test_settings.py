# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Configuration, acronyms and prompts, on the test store."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("MYSQL_USER"), reason="MYSQL_* not set"
)


def test_a_configuration_value_is_upserted() -> None:
    from auto_ontology.dal import settings

    settings.set_configuration("visualization_enabled", "false")
    settings.set_configuration("visualization_enabled", "true")
    assert settings.get_configuration("visualization_enabled") == "true"
    assert settings.get_configuration("never_set") is None


def test_acronym_lifecycle() -> None:
    from auto_ontology.dal import settings

    created = settings.create_acronym("ARR", "Annual recurring revenue")
    assert settings.find_acronym("ARR")["id"] == created["id"]
    updated = settings.update_acronym(
        created["id"], description="Annualised recurring revenue"
    )
    assert updated["description"] == "Annualised recurring revenue"
    assert settings.delete_acronym(created["id"])
    assert settings.find_acronym("ARR") is None
    assert settings.update_acronym(created["id"], description="x") is None


def test_prompt_lifecycle() -> None:
    from auto_ontology.dal import settings

    prompt = settings.create_prompt("Prefer invoice dates over order dates.")
    assert settings.get_prompt(prompt["id"])["content"].startswith("Prefer")
    assert settings.update_prompt(prompt["id"], "Use UTC.")["content"] == "Use UTC."
    assert settings.delete_prompt(prompt["id"])
    assert settings.get_prompt(prompt["id"]) is None


def test_ontology_yaml_switches_seed_only_unset_keys() -> None:
    from types import SimpleNamespace

    from auto_ontology.dal import schema as s
    from auto_ontology.dal import settings
    from auto_ontology.dal.session import store
    from auto_ontology.infra.feature_flags import seed_from_config

    store().query_write(s.configurations.delete())
    settings.set_configuration("pii_detection_enabled", "true")
    config = SimpleNamespace(
        semantic_compilation=True, pii_detection=False, distinct_value_probing=False
    )
    assert seed_from_config(config) == [
        "semantic_compilation_enabled",
        "distinct_value_probing_enabled",
    ]
    assert settings.get_configuration("pii_detection_enabled") == "true"
    assert settings.get_configuration("semantic_compilation_enabled") == "true"
    assert settings.get_configuration("distinct_value_probing_enabled") == "false"
    assert seed_from_config(config) == []
