# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Index creation — a no-op, because the migration runner owns the schema.

Indexes and constraints are declared in ``auto_ontology/dal/schema.py`` and
created by :mod:`auto_ontology.dal.migrations`, so there is nothing for an
ingest to do. Kept as a function because ``write.populate_tabular_data`` calls
it unconditionally.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def add_indices() -> None:
    """Do nothing. Indexes are created by migration, not by ingestion."""
    logger.debug("add_indices: no-op; indexes come from the migration runner")
