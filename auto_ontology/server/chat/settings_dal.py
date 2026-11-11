# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Read user-configured acronyms and custom prompts for the chat agent.

The chat router pulls them on every request and injects them into the
text-to-SQL agent payload, so the client does not ship them on the wire.
"""

from __future__ import annotations

import logging

from auto_ontology.dal import settings

logger = logging.getLogger(__name__)


def fetch_acronyms() -> list[dict[str, str]]:
    """Return acronyms as ``[{"name": ..., "description": ...}, ...]``.

    Shape matches ``AgentState.acronyms`` / the dicts
    consumed by ``rules_to_text`` in the text-to-SQL pipeline.
    """
    try:
        return [
            {"name": row["name"], "description": row["description"]}
            for row in settings.list_acronyms()
        ]
    except Exception:
        # Settings are best-effort: a DB hiccup here must not break chat.
        logger.exception("Failed to fetch acronyms; continuing with empty list")
        return []


def is_visualization_enabled() -> bool:
    """Instance-wide "Visualize SQL Results" toggle (Settings > Agent Settings).

    A missing row or a DB hiccup both count as enabled — the feature is on by default and a
    transient read failure shouldn't silently suppress every chart.
    """
    try:
        return settings.get_configuration("visualization_enabled") != "false"
    except Exception:
        logger.exception("Failed to read visualization setting; defaulting to enabled")
        return True


def fetch_custom_prompts() -> str:
    """Return all stored prompts joined into one string (blank if none).

    The agent embeds this verbatim into the system prompt
    (see ``auto_ontology.retrieval.text_to_sql.main._build_state``).
    """
    try:
        rows = settings.list_prompts()
    except Exception:
        logger.exception("Failed to fetch custom prompts; continuing with empty string")
        return ""

    contents = [row["content"] for row in rows if row["content"]]
    return "\n\n".join(contents)
