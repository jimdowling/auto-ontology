# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Replaying the tagging rules once a job has finished changing the catalog.

A rule is a standing instruction rather than a one-off labelling (see
``auto_ontology.server.rules.service``), so the ingest and compile jobs replay
every rule over what they changed.
"""

from __future__ import annotations

import logging

from auto_ontology.server.rules.service import reapply_rules

logger = logging.getLogger(__name__)


def replay_rules(label: str) -> None:
    """Re-label the catalog through every stored rule, swallowing a failure.

    *label* prefixes the log line with the pass that asked, matching the
    scheduler log prefixes.

    A failure here must not fail the pass that called it. Per-rule failures are
    already contained one level down, so reaching this handler means the whole
    rule pass could not run -- and recording the *ingest* or the *compilation*
    as failed for it would put a red state on the settings page against work
    that in fact succeeded.
    """
    try:
        reapply_rules()
    except Exception:
        logger.exception("%s: could not re-apply tagging rules", label)
