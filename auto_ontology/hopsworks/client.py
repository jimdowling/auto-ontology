# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The process's Hopsworks login.

Inside a Hopsworks job or app, ``hopsworks.login()`` reads the platform's JWT
from ``SECRETS_DIR``; the platform renews that file for a running app, and the
client re-reads it after a 401. The client is process-global, which is why every
caller goes through :func:`login` instead of logging in on its own.
"""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_project: Any = None


def login() -> Any:
    """The logged-in project, logging in on first use. Thread-safe."""
    global _project
    with _lock:
        if _project is None:
            import hopsworks

            _project = hopsworks.login()
        return _project


def feature_store(name: str | None = None) -> Any:
    """The named feature store, or the project's default when ``name`` is None."""
    project = login()
    return project.get_feature_store(name) if name else project.get_feature_store()
