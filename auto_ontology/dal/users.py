# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Zone scoping: which catalog a set of zones lets you see.

This is the access-control boundary. Nearly every read in the DAL takes a
``zone_ids`` argument and narrows itself through here, so a mistake does not
show up as a wrong answer — it shows up as one user seeing another's data.
Treated accordingly: the expansion rules are spelled out, and the tests cover
each one separately rather than in aggregate.

Two entry points: :func:`resolve_accessible_catalog_ids` returns the id sets a
caller can see, and :func:`resolve_table_filter` turns those into a predicate to
hand to ``.where()``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import literal, select, union

from auto_ontology.dal import schema as s
from auto_ontology.dal.session import store


def _accessible_ids_statement(zone_ids: list[str]) -> Any:
    """``(kind, id)`` rows for every catalog id *zone_ids* reach, in one query,
    where ``kind`` is ``db_ids``, ``schema_ids`` or ``table_ids``.

    Expansion runs **one level from each direct grant**, and not transitively:
    granting a table admits its schema, but not that schema's other tables.
    Every branch reads from ``granted`` rather than from another branch, which
    is what keeps it non-recursive.
    """
    target, table, schema = s.zone_target, s.catalog_table, s.catalog_schema
    granted = (
        select(target.c.database_id, target.c.schema_id, target.c.table_id)
        .where(target.c.zone_id.in_(zone_ids))
        .cte("granted")
    )

    def rows(kind: str, column: Any) -> Any:
        return select(literal(kind).label("kind"), column.label("id"))

    return union(
        # Tables: granted directly, under a granted schema, under a granted database.
        rows("table_ids", granted.c.table_id).where(granted.c.table_id.isnot(None)),
        rows("table_ids", table.c.id).select_from(
            table.join(granted, granted.c.schema_id == table.c.schema_id)
        ),
        rows("table_ids", table.c.id).select_from(
            table.join(schema, schema.c.id == table.c.schema_id).join(
                granted, granted.c.database_id == schema.c.database_id
            )
        ),
        # Schemas: granted directly, under a granted database, the parent of a
        # granted table.
        rows("schema_ids", granted.c.schema_id).where(granted.c.schema_id.isnot(None)),
        rows("schema_ids", schema.c.id).select_from(
            schema.join(granted, granted.c.database_id == schema.c.database_id)
        ),
        rows("schema_ids", table.c.schema_id).select_from(
            table.join(granted, granted.c.table_id == table.c.id)
        ),
        # Databases: granted directly, the parent of a granted schema, the
        # grandparent of a granted table.
        rows("db_ids", granted.c.database_id).where(granted.c.database_id.isnot(None)),
        rows("db_ids", schema.c.database_id).select_from(
            schema.join(granted, granted.c.schema_id == schema.c.id)
        ),
        rows("db_ids", schema.c.database_id).select_from(
            schema.join(table, table.c.schema_id == schema.c.id).join(
                granted, granted.c.table_id == table.c.id
            )
        ),
    )


def get_accessible_catalog_ids_for_zones(
    zone_ids: list[str],
) -> dict[str, set[str]]:
    """Return the catalog ids reachable through *zone_ids*.

    Receives zones already scoped to the requesting user; it does not consult
    the user itself.

    Parents are included so the catalog tree can be rendered: a zone granting a
    table also admits that table's schema and database. Children are included
    the other way: a zone granting a database admits its schemas and their
    tables. Neither direction is transitive.
    """
    found: dict[str, set[str]] = {
        "db_ids": set(),
        "schema_ids": set(),
        "table_ids": set(),
    }
    if not zone_ids:
        return found

    for row in store().query_read(_accessible_ids_statement(list(zone_ids))):
        if row["id"]:
            found[row["kind"]].add(row["id"])
    return found


def resolve_accessible_catalog_ids(
    zone_ids: list[str] | None,
    data_ids_by_zone: dict[str, set[str]] | None = None,
) -> dict[str, set[str]] | None:
    """Resolve *zone_ids* to accessible catalog ids, reusing a prior result.

    ``None`` means no zone scoping at all — an admin or internal caller seeing
    the whole catalog. That is emphatically not the same as an empty list, which
    grants nothing, and conflating the two is how an access-control bug gets
    written.

    Callers needing the ids more than once in a request (the exploration graph
    builders combine node, zone-map and edge queries) resolve once and thread
    the result through as *data_ids_by_zone*.
    """
    if zone_ids is None:
        return None
    if data_ids_by_zone is not None:
        return data_ids_by_zone
    return get_accessible_catalog_ids_for_zones(zone_ids)


def resolve_table_filter(
    zone_ids: list[str] | None,
    column_ref: Any,
    *,
    data_ids_by_zone: dict[str, set[str]] | None = None,
) -> Any:
    """A predicate restricting *column_ref* to the tables *zone_ids* can see.

    *column_ref* is a SQLAlchemy column — ``catalog_table.c.id``,
    ``column_attribute.c.table_id`` — and the result goes to ``.where()``.

    ``zone_ids is None`` yields ``None``: no filter, full catalog. An **empty
    list** yields a predicate matching nothing, because "scoped to no zones" has
    to deny rather than permit. Conflating the two is how an access-control bug
    gets written.
    """
    if zone_ids is None:
        return None
    resolved = resolve_accessible_catalog_ids(zone_ids, data_ids_by_zone)
    return column_ref.in_(list(resolved["table_ids"]))
