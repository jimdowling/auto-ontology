# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The semantic-compilation switch, stored in ``configurations`` by Settings.

The history of compilation passes lives in ``semantic_compilation_history``;
see ``history.py``.
"""

from __future__ import annotations

import logging

from auto_ontology.infra.feature_flags import read_configuration_flag

logger = logging.getLogger(__name__)

# Key stored in the ``configurations`` table by the Semantic Compilation
# settings tab. Its value is the string ``"true"`` or ``"false"``.
SEMANTIC_COMPILATION_ENABLED_KEY = "semantic_compilation_enabled"


def is_semantic_compilation_enabled() -> bool:
    """Return whether semantic compilation is enabled in settings.

    Opt-in: a missing row (or any DB error) is treated as "disabled", so an
    instance that has never enabled it never starts compiling on its own.
    """
    return read_configuration_flag(SEMANTIC_COMPILATION_ENABLED_KEY, default=False)
