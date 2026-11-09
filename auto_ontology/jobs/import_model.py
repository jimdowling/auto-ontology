# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Import a model export (native or Apache Ossie YAML) from a project file.

For exports too large to upload through the app's import page in one request:
the YAML is read from the project path given with ``--file``, applied, and
embedded. ``--merge`` keeps existing definitions the file does not mention,
instead of replacing them.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from auto_ontology.jobs.runtime import pipeline_lease

logger = logging.getLogger(__name__)


def _read(path: str) -> str:
    local = Path(path)
    if not local.is_file():
        local = Path("/hopsfs") / path
    if not local.is_file():
        from auto_ontology.hopsworks.client import login

        local = Path(login().get_dataset_api().download(path, "/tmp", overwrite=True))
    return local.read_text(encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="import")
    parser.add_argument(
        "--file", required=True, help="project-relative path of the YAML"
    )
    parser.add_argument("--merge", action="store_true")
    args = parser.parse_args(argv)
    from auto_ontology.server.model_interchange.service import import_model

    with pipeline_lease():
        summary = import_model(_read(args.file), replace=not args.merge, embed=True)
    logger.info("Imported %s: %s", args.file, summary)
    return 0
