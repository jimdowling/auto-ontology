# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The caller, and the project members who can be shown as owners."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from auto_ontology.hopsworks.identity import Caller, member_roles
from auto_ontology.server.authz import current_caller
from auto_ontology.server.responses import OwnerListResponse
from auto_ontology.server.users.permissions import permissions_for_role

router = APIRouter()


@router.get("/me")
def me(caller: Caller = Depends(current_caller)) -> dict:
    """The verified caller: Hopsworks username, ontology role and its permissions."""
    return {
        "username": caller.username,
        "role": caller.role,
        "permissions": permissions_for_role(caller.role),
    }


@router.get("/owners", response_model=OwnerListResponse)
def list_owners() -> dict:
    """Every project member, with the permissions of their ontology role.

    A picker uses the permissions to offer only the members who may own that
    kind of object. Groups do not exist on Hopsworks, so every row is a user.
    """
    owners = [
        {
            "id": username,
            "name": (member_roles.profile(username) or {}).get("name", username),
            "kind": "user",
            "color": None,
            "permissions": permissions_for_role(role),
            "member_ids": [],
        }
        for username, role in member_roles.all().items()
    ]
    owners.sort(key=lambda owner: owner["name"].lower())
    return {"data": owners, "count": len(owners)}
