# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Who may be chosen as an owner, and who may edit a row.

An owner is a project member. A member may edit a row when their ontology role
grants the required permission, or when they own the row. Groups, which
upstream also allowed as owners, do not exist on Hopsworks.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from auto_ontology.dal.owners import EditSubject
from auto_ontology.hopsworks.identity import member_roles
from auto_ontology.server.users.permissions import permissions_for_role


class UnassignableOwner(ValueError):
    """The id is not a member allowed to own this kind of row."""

    def __init__(self, owner_id: str) -> None:
        self.owner_id = owner_id
        super().__init__(f"Owner {owner_id!r} is not a member who can edit this")


def normalize_owner_id(value: str | None) -> str | None:
    """Blank means unassigned. A non-blank id is returned trimmed."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def decide_edit(*, role: str | None, permission: str) -> bool:
    """Whether a member with ``role`` may edit a row gated by ``permission``."""
    return role == "admin" or permission in permissions_for_role(role or "")


def require_assignable(owner_id: str | None, permission: str) -> str | None:
    """``owner_id`` when that member may own a row gated by ``permission``, or
    ``None`` to clear. Raises :class:`UnassignableOwner` otherwise."""
    if owner_id is None:
        return None
    role = member_roles.role(owner_id)
    if role is not None and decide_edit(role=role, permission=permission):
        return owner_id
    raise UnassignableOwner(owner_id)


def enforce_edit(request: Request, subject: EditSubject) -> None:
    """403 unless the caller's role grants the edit or the caller owns the row."""
    caller = getattr(request.state, "caller", None)
    if caller is None:
        raise HTTPException(status_code=401, detail="No verified caller")
    if decide_edit(role=caller.role, permission=subject.permission):
        return
    if subject.owner_id is not None and subject.owner_id == caller.username:
        return
    raise HTTPException(
        status_code=403, detail="You do not have permission to edit this"
    )


def owner_from_body(value: str | None, permission: str) -> str | None:
    """The owner a write asked for, or 400 when it cannot be assigned."""
    try:
        return require_assignable(normalize_owner_id(value), permission)
    except UnassignableOwner as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
