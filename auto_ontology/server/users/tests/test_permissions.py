# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The permissions each ontology role holds."""

from __future__ import annotations

import json
from importlib import resources

from auto_ontology.server.users.permissions import ROLES, permissions_for_role


def test_the_three_roles_nest() -> None:
    reader = set(permissions_for_role("reader"))
    editor = set(permissions_for_role("editor"))
    admin = set(permissions_for_role("admin"))
    assert reader < editor < admin


def test_readers_cannot_chat_or_see_conversations() -> None:
    reader = set(permissions_for_role("reader"))
    assert "chat:use" not in reader
    assert not {p for p in reader if p.startswith("conversation:")}


def test_editors_edit_the_catalog_but_not_the_settings() -> None:
    editor = set(permissions_for_role("editor"))
    assert {"catalog:edit", "analysis:manage", "chat:use"} <= editor
    assert "semanticCompilation:manage" not in editor
    assert "connection:manage" not in editor


def test_an_unknown_role_grants_nothing() -> None:
    assert permissions_for_role("viewer") == []


def test_no_role_names_an_upstream_only_resource() -> None:
    raw = json.loads(
        resources.files("auto_ontology.server.users")
        .joinpath("access.json")
        .read_text()
    )
    assert set(raw) == set(ROLES)
    for grants in raw.values():
        assert not set(grants) & {"sso", "zone", "group", "apiToken"}
