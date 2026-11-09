# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read instance-wide settings from the ``configurations`` table.

Flag values are the strings ``"true"`` / ``"false"``; numeric
settings are stored as decimal integer strings.

Each flag carries its own default for the "row absent or unreadable" case, and
the defaults genuinely differ: semantic compilation and PII detection are
opt-in (absent means off), while column profiling is opt-out (absent means on,
so existing instances keep profiling after an upgrade that adds the toggle).
On Hopsworks a new system's ``ontology.yaml`` sets all three
(:func:`seed_from_config`), compilation on unless it says otherwise.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from auto_ontology.hopsworks.config import OntologyConfig

logger = logging.getLogger(__name__)

# Written by the Semantic Compilation settings tab. Opt-out: an instance that
# has never touched the toggle still probes, which is what every deployment
# predating the toggle did.
DISTINCT_VALUE_PROBING_ENABLED_KEY = "distinct_value_probing_enabled"

# Written by the PII Settings tab. Opt-in: ingest does not classify columns
# until an admin turns the toggle on.
PII_DETECTION_ENABLED_KEY = "pii_detection_enabled"

# Written by the SQL Query Timeout field on Settings > Agent Settings: how long
# a statement the text-to-SQL agent issues may run before it is cancelled. An
# instance without the frontend never writes the row and gets the default.
SQL_QUERY_TIMEOUT_SECONDS_KEY = "sql_query_timeout_seconds"
DEFAULT_SQL_QUERY_TIMEOUT_SECONDS = 30
# Mirrored by the frontend's input bounds; a stored value outside them is
# treated like junk rather than clamped, so both sides agree on what it means.
MIN_SQL_QUERY_TIMEOUT_SECONDS = 1
MAX_SQL_QUERY_TIMEOUT_SECONDS = 3600


def _read_configuration_row(key: str) -> tuple[object, ...] | None:
    """Return the ``(value,)`` row for *key*, or ``None`` if it is absent."""
    from auto_ontology.dal.settings import get_configuration

    value = get_configuration(key)
    return None if value is None else (value,)


def read_configuration_flag(key: str, *, default: bool) -> bool:
    """Return the boolean value of *key*, or *default* when it cannot be read.

    Best-effort by design: any DB error (including the table not existing yet,
    which is the case before the app's first migration) falls back to
    *default* rather than raising, so a missing or unreachable config never
    crashes a service at startup.
    """
    try:
        row = _read_configuration_row(key)
    except Exception:
        logger.exception("Failed to read %s; falling back to %s", key, default)
        return default

    if not row:
        return default
    # Only the two values the frontend writes count as a decision. Anything
    # else -- an empty string, "1", "yes", a hand-edited or seeded row -- falls
    # back to *default*, because the alternative is a silent disagreement: the
    # frontend reads an opt-out flag as `value !== 'false'`, so a junk value
    # renders the toggle ON while this returned False and stopped the work.
    value = str(row[0]).strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    logger.warning(
        "Configuration %s holds unrecognised value %r; using default %s",
        key,
        row[0],
        default,
    )
    return default


def is_distinct_value_probing_enabled() -> bool:
    """Whether compilation may run per-column ``SELECT DISTINCT`` probes.

    Scoped to those probes only. The bounded ``SELECT * ... LIMIT 1000`` row
    sample always runs -- it is one cheap query per table. The DISTINCT probes
    are the unbounded ones: one per low-cardinality text column, and a full
    column scan on warehouses where ``DISTINCT`` + ``LIMIT`` does not
    early-stop, which is what makes them worth switching off on a large or
    metered warehouse.
    """
    return read_configuration_flag(DISTINCT_VALUE_PROBING_ENABLED_KEY, default=True)


def is_pii_detection_enabled() -> bool:
    """Whether ingest may classify catalog columns and attach the ``PII`` tag.

    Opt-in: a missing row (or any DB error) is treated as disabled, so an
    instance that has never touched Settings > PII Settings never classifies
    on its own. Read per ingest, so a change applies to the next database
    without a restart.
    """
    return read_configuration_flag(PII_DETECTION_ENABLED_KEY, default=False)


def read_configuration_int(
    key: str, *, default: int, minimum: int, maximum: int
) -> int:
    """Return the integer value of *key*, or *default* when it cannot be used.

    Best-effort in the same way as :func:`read_configuration_flag`: a DB error,
    a missing row, a non-integer value or one outside ``[minimum, maximum]``
    all fall back to *default*.
    """
    try:
        row = _read_configuration_row(key)
    except Exception:
        logger.exception("Failed to read %s; falling back to %s", key, default)
        return default

    if not row:
        return default
    try:
        value = int(str(row[0]).strip())
    except ValueError:
        value = None
    if value is not None and minimum <= value <= maximum:
        return value
    logger.warning(
        "Configuration %s holds unusable value %r; using default %s",
        key,
        row[0],
        default,
    )
    return default


def get_sql_query_timeout_seconds() -> int:
    """How long one agent-issued SQL statement may run, in seconds.

    Read per statement, so a change on Settings > Agent Settings applies to the
    next query without a restart. Defaults to
    :data:`DEFAULT_SQL_QUERY_TIMEOUT_SECONDS` when nobody has set it.
    """
    return read_configuration_int(
        SQL_QUERY_TIMEOUT_SECONDS_KEY,
        default=DEFAULT_SQL_QUERY_TIMEOUT_SECONDS,
        minimum=MIN_SQL_QUERY_TIMEOUT_SECONDS,
        maximum=MAX_SQL_QUERY_TIMEOUT_SECONDS,
    )


def seed_from_config(config: OntologyConfig) -> list[str]:
    """Store ``ontology.yaml``'s switches for every key Settings has never set;
    returns the keys stored. After that the Settings page is the record."""
    from auto_ontology.dal.settings import seed_configuration
    from auto_ontology.ingestion_service.config import SEMANTIC_COMPILATION_ENABLED_KEY

    switches = {
        SEMANTIC_COMPILATION_ENABLED_KEY: config.semantic_compilation,
        PII_DETECTION_ENABLED_KEY: config.pii_detection,
        DISTINCT_VALUE_PROBING_ENABLED_KEY: config.distinct_value_probing,
    }
    return [
        key
        for key, enabled in switches.items()
        if seed_configuration(key, "true" if enabled else "false")
    ]
