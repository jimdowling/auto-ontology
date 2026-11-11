# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Permissions each ontology role holds.

A Hopsworks project role maps to one ontology role
(:data:`auto_ontology.hopsworks.identity.PROJECT_ROLES`): Data owners are
``admin``, Data scientists ``editor``, Observers and feature-store-restricted
members ``reader``. ``access.json`` lists each role's ``resource: [actions]``,
the same vocabulary as upstream's public API permissions, so the route
permissions generated from that spec apply unchanged.
"""

from __future__ import annotations

from importlib import resources
import json
from typing import Any

ROLES = ("admin", "editor", "reader")

_ACCESS_RESOURCE = resources.files(__package__).joinpath("access.json")


def _invalid(message: str) -> RuntimeError:
    return RuntimeError(f"Invalid packaged permission resource access.json: {message}")


def _resources_for_role(raw: Any, role: str) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        raise _invalid("top-level value must be an object")
    resources_by_role = raw.get(role)
    if not isinstance(resources_by_role, dict):
        raise _invalid(f"missing object for role {str(role)!r}")

    validated: dict[str, list[str]] = {}
    for resource, actions in resources_by_role.items():
        if not isinstance(resource, str) or not resource:
            raise _invalid(f"role {str(role)!r} contains an invalid resource name")
        if (
            not isinstance(actions, list)
            or not actions
            or not all(isinstance(action, str) and action for action in actions)
        ):
            raise _invalid(
                f"actions for role {str(role)!r}, resource {resource!r} "
                "must be a non-empty string list"
            )
        validated[resource] = actions
    return validated


def _load() -> dict[str, list[str]]:
    try:
        text = _ACCESS_RESOURCE.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            "Packaged permission resource access.json is missing or unreadable"
        ) from exc
    except UnicodeError as exc:
        raise _invalid("content must be UTF-8") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _invalid(f"malformed JSON ({exc.msg})") from exc

    loaded: dict[str, list[str]] = {}
    for role in ROLES:
        resources = _resources_for_role(raw, role)
        loaded[role] = [
            f"{resource}:{action}"
            for resource, actions in resources.items()
            for action in actions
        ]
    return loaded


_BY_ROLE = _load()


def permissions_for_role(role: str) -> list[str]:
    """``resource:action`` strings for *role*, or nothing for an unknown one.

    An unknown role grants nothing.
    """
    return list(_BY_ROLE.get(role, ()))
