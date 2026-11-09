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
