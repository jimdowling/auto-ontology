# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Auto Ontology data access layer, organised by topic.

Each module is the single source of truth for a domain:
  datasources       — Database / Schema / Table / Column catalog
  terms             — Term CRUD and synonym reads (semantic compilation)
  attributes        — ColumnAttribute, SEMANTIC_FK, join path traversal
  custom_analyses   — CustomAnalysis and its SQL
  pql_analyses      — PqlAnalysis, a question paired with a KumoRFM PQL query
  sql_attributes    — SqlAttribute and its SQL
  connections       — The ontology's sources: the Hopsworks data source each
                      catalog database is read from, never its credentials
  reset             — Deleting a database's catalog/semantic rows and embeddings
  candidates        — Vector-hit enrichment at retrieval time
  exploration       — The data- and semantic-layer Exploration graphs
  model_interchange — Model YAML export and import
  search            — Substring global search across catalog and semantic rows
  settings          — Configuration flags, acronyms and custom prompts
  users             — Zone-scope helpers. Accounts are Hopsworks project members.
  groups            — User groups and their membership; a membership stores a
                      Hopsworks username with no foreign key.

``schema`` holds the SQLAlchemy Core table metadata, ``session`` the pooled
engine, ``ops`` the write idioms MySQL lacks (``RETURNING``, targeted upserts)
and ``migrations`` the recorded schema steps; everything else queries through
them.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def close_store() -> None:
    """Release every connection the DAL holds. Idempotent.

    The public shutdown hook, so callers do not reach into driver internals.
    Deferred import keeps importing :mod:`auto_ontology.dal` cheap and leaves this module
    with no import-time dependency on SQLAlchemy.

    One connection to release: the pooled engine. ``dispose_engine`` is already
    idempotent and already swallows its own failures, so there is nothing left
    for this function to add beyond being the name callers know.
    """
    from auto_ontology.dal.session import dispose_engine

    dispose_engine()
