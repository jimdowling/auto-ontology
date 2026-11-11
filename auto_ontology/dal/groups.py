# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""User groups and their members.

Accounts are Hopsworks project members, which this module does not read: a
membership stores a Hopsworks username with no foreign key, and a member is
shown by that stored id. Whether an id names a project member, and which
project role it holds, is the caller's to ask Hopsworks.
"""

from __future__ import annotations

from typing import Any, NoReturn

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from auto_ontology.dal import schema as s
from auto_ontology.dal.ops import delete_returning, insert_returning
from auto_ontology.dal.session import store, write_transaction

_GROUP_COLUMNS = (
    s.user_group.c.id,
    s.user_group.c.name,
    s.user_group.c.description,
    s.user_group.c.color,
    s.user_group.c.role,
    s.user_group.c.created,
)


class GroupNameTaken(ValueError):
    """Another group already holds this name, case-insensitively."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Group with name {name!r} already exists")


def _require_role(role: str) -> None:
    if role not in (s.GROUP_ROLE_ADMIN, s.GROUP_ROLE_VIEWER):
        raise ValueError(f"Role must be admin or viewer, got {role!r}")


def _name_taken(name: str, *, exclude_id: str | None = None) -> bool:
    statement = select(s.user_group.c.id).where(
        s.user_group.c.name_key == name.strip().lower()
    )
    if exclude_id is not None:
        statement = statement.where(s.user_group.c.id != exclude_id)
    return bool(store().query_read(statement))


def _user_view(user_id: str) -> dict[str, Any]:
    return {"id": user_id, "name": user_id}


def _attach_users(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not groups:
        return []
    group_ids = [group["id"] for group in groups]
    member_rows = store().query_read(
        select(
            s.user_group__member.c.group_id,
            s.user_group__member.c.user_id,
        ).where(s.user_group__member.c.group_id.in_(group_ids))
    )
    members: dict[str, list[str]] = {}
    for row in member_rows:
        members.setdefault(row["group_id"], []).append(row["user_id"])

    attached: list[dict[str, Any]] = []
    for group in groups:
        users = [_user_view(user_id) for user_id in members.get(group["id"], [])]
        users.sort(key=lambda user: (user["name"].lower(), user["id"]))
        attached.append(
            {
                **group,
                "description": group["description"] or "",
                "users": users,
            }
        )
    return attached


def _group_rows(
    *, group_id: str | None = None, user_id: str | None = None
) -> list[dict[str, Any]]:
    statement = select(*_GROUP_COLUMNS).order_by(
        func.lower(s.user_group.c.name), s.user_group.c.id
    )
    if user_id is not None:
        statement = statement.join(
            s.user_group__member,
            s.user_group__member.c.group_id == s.user_group.c.id,
        ).where(s.user_group__member.c.user_id == user_id)
    if group_id is not None:
        statement = statement.where(s.user_group.c.id == group_id)
    return _attach_users(store().query_read(statement))


def _insert_members(group_id: str, user_ids: list[str]) -> None:
    if not user_ids:
        return
    store().query_write(
        s.user_group__member.insert().values(
            [{"group_id": group_id, "user_id": user_id} for user_id in user_ids]
        )
    )


def _replace_members(group_id: str, user_ids: list[str]) -> None:
    store().query_write(
        s.user_group__member.delete().where(s.user_group__member.c.group_id == group_id)
    )
    _insert_members(group_id, user_ids)


def _raise_name_taken(exc: IntegrityError, name: str) -> NoReturn:
    if "uq_user_group_name_lower" not in str(exc.orig):
        raise exc
    raise GroupNameTaken(name) from exc


def list_groups() -> list[dict[str, Any]]:
    """Every group, ordered by name, each with its members."""
    return _group_rows()


def get_group(group_id: str) -> dict[str, Any] | None:
    """One group with its members, or ``None`` when the id is unknown."""
    rows = _group_rows(group_id=group_id)
    return rows[0] if rows else None


def groups_for_user(user_id: str) -> list[dict[str, Any]]:
    """The groups *user_id* belongs to, ordered by name."""
    return _group_rows(user_id=user_id)


def list_users_and_groups() -> dict[str, Any]:
    """Every group, and every id that is a member of one.

    ``users`` holds only ids found in a membership, ordered by id, each with
    the ids of its groups in group-name order. A project member in no group is
    absent; the caller lists project members from Hopsworks.
    """
    groups = list_groups()
    group_ids: dict[str, list[str]] = {}
    for group in groups:
        for user in group["users"]:
            group_ids.setdefault(user["id"], []).append(group["id"])
    users = [
        {**_user_view(user_id), "groups": group_ids[user_id]}
        for user_id in sorted(group_ids, key=lambda user_id: (user_id.lower(), user_id))
    ]
    return {"users": users, "groups": groups}


def create_group(
    *,
    name: str,
    description: str | None,
    color: str,
    role: str,
    user_ids: list[str],
) -> dict[str, Any]:
    """Create a group and its membership, and return the group.

    *name* is stored as given; the caller trims it. *user_ids* are stored
    unchecked. Raises :class:`GroupNameTaken` when the name is already held.
    """
    _require_role(role)
    if _name_taken(name):
        raise GroupNameTaken(name)

    try:
        with write_transaction():
            rows = insert_returning(
                s.user_group,
                {
                    "name": name,
                    "description": description,
                    "color": color,
                    "role": role,
                },
                [s.user_group.c.id],
            )
            group_id = rows[0]["id"]
            _insert_members(group_id, user_ids)
    except IntegrityError as exc:
        _raise_name_taken(exc, name)

    group = get_group(group_id)
    if group is None:  # pragma: no cover - the insert just returned this id
        raise RuntimeError(f"Group {group_id!r} missing after insert")
    return group


def update_group(
    *,
    group_id: str,
    updates: dict[str, Any],
    user_ids: list[str] | None,
) -> dict[str, Any] | None:
    """Update a group's fields and, when given, replace its members.

    ``None`` when no group has that id. *user_ids* ``None`` leaves membership
    alone; a list replaces it, including the empty list.

    The group row is locked for the write. A delete that lands first comes
    back as ``None`` instead of a foreign-key error, and two membership
    replacements of the same group run one after the other.

    Raises :class:`GroupNameTaken` as :func:`create_group` does. A group's own
    name is not a collision.
    """
    if "role" in updates:
        _require_role(updates["role"])

    try:
        with write_transaction():
            locked = store().query_read(
                select(s.user_group.c.id)
                .where(s.user_group.c.id == group_id)
                .with_for_update()
            )
            if not locked:
                return None
            if "name" in updates and _name_taken(updates["name"], exclude_id=group_id):
                raise GroupNameTaken(updates["name"])
            if updates:
                store().query_write(
                    s.user_group.update()
                    .where(s.user_group.c.id == group_id)
                    .values(**updates)
                )
            if user_ids is not None:
                _replace_members(group_id, user_ids)
    except IntegrityError as exc:
        if "name" in updates:
            _raise_name_taken(exc, updates["name"])
        raise

    return get_group(group_id)


def delete_group(group_id: str) -> bool:
    """Delete one group. Membership goes with it. ``False`` when it is absent."""
    return bool(
        delete_returning(
            s.user_group, s.user_group.c.id == group_id, [s.user_group.c.id]
        )
    )
