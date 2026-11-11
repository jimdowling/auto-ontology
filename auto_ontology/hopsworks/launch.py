# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Entry points for the ontology app and jobs on Hopsworks.

The factory copies two-line launchers into the system directory; each calls
:func:`app` or :func:`job`. Both bootstrap the process before importing the
rest of Auto Ontology, because the schema and the model clients read their
environment at import time:

1. find and load ``ontology.yaml`` (``--config``, ``ONTOLOGY_CONFIG``, or ``./ontology.yaml``);
2. log in to Hopsworks and set ``ONTOLOGY_TABLE_PREFIX`` from the app's table prefix;
3. for a job, set ``MYSQL_*`` from the member's online storage connector (the
   app gets them from the platform);
4. set the model environment (:mod:`auto_ontology.hopsworks.models`).
"""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import sys
from importlib import import_module
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_app_handle: Any = None

#: Job step names to their modules under auto_ontology.jobs.
JOB_MODULES = {
    "ingest": "ingest",
    "compile": "compile",
    "embed": "embed",
    "reset": "reset",
    "import": "import_model",
}


def _arguments(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    if isinstance(value, list):
        return {
            str(item["name"]): str(item["value"])
            for item in value
            if isinstance(item, dict)
        }
    if isinstance(value, str):
        pairs = (part.split("=", 1) for part in value.split(",") if "=" in part)
        return {key.strip(): val.strip() for key, val in pairs}
    return {}


def _job_database_env(feature_store: Any) -> None:
    connector = feature_store.get_online_storage_connector()
    parsed = urlparse(connector.connection_string.removeprefix("jdbc:"))
    arguments = _arguments(connector.arguments)
    os.environ["MYSQL_HOST"] = parsed.hostname or ""
    os.environ["MYSQL_PORT"] = str(parsed.port or 3306)
    os.environ["MYSQL_DB"] = parsed.path.lstrip("/")
    os.environ["MYSQL_USER"] = arguments["user"]
    os.environ["MYSQL_PASSWORD"] = arguments["password"]


def bootstrap(argv: list[str], *, job: bool) -> list[str]:
    """Prepare the process environment; returns the arguments left for the step."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config")
    # Appended by Hopsworks to every scheduled run; no step uses them.
    parser.add_argument("-start_time")
    parser.add_argument("-end_time")
    known, rest = parser.parse_known_args(argv)
    if known.config:
        os.environ["ONTOLOGY_CONFIG"] = known.config

    from auto_ontology.hopsworks import models
    from auto_ontology.hopsworks.client import feature_store, login
    from auto_ontology.hopsworks.config import load

    global _app_handle
    config = load()
    project = login()
    _app_handle = project.get_app_api().get_app(config.app)
    if _app_handle is None:
        raise RuntimeError(f"app {config.app!r} does not exist in this project")
    os.environ["ONTOLOGY_TABLE_PREFIX"] = _app_handle.table_prefix or ""
    if job:
        _job_database_env(feature_store(config.feature_store))
    chosen = models.configure(config)
    logger.info("Ontology %s: models %s", config.name, chosen)
    return rest


def app_handle() -> Any:
    """The Hopsworks app object, once :func:`bootstrap` has run; otherwise ``None``."""
    return _app_handle


def _in_spawned_child() -> bool:
    # A spawned process (the chat worker) re-runs the launcher file that called app()
    # or job() before it runs its own target; there, starting a second server or job
    # would fail on the port or rerun the step instead of answering the question.
    return multiprocessing.parent_process() is not None


def app() -> None:
    """Run the ontology app (API and UI) on ``APP_PORT``. Does nothing in a spawned child process."""
    if _in_spawned_child():
        return
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    bootstrap(sys.argv[1:], job=False)
    from auto_ontology.server.__main__ import main

    main(port=int(os.environ.get("APP_PORT", "8080")))


def job(step: str) -> None:
    """Run one pipeline step (``ingest``, ``compile``, ``embed``, ``reset``, ``import``).
    Does nothing in a spawned child process."""
    if _in_spawned_child():
        return
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    rest = bootstrap(sys.argv[1:], job=True)
    module = import_module(f"auto_ontology.jobs.{JOB_MODULES[step]}")
    sys.exit(module.main(rest))
