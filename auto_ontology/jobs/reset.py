# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Remove a layer of the ontology.

``--semantic`` deletes the semantic layer (of one database with ``--database``,
otherwise of all) with its vectors, then compiles it again. ``--all`` deletes a
database's catalog and semantic layer and their vectors, which is what removing
a source does; it requires ``--database``.
"""

from __future__ import annotations

import argparse
import logging

from auto_ontology.dal.reset import delete_all_data, delete_semantic_layer
from auto_ontology.jobs.compile import compile_all
from auto_ontology.jobs.runtime import pipeline_lease

logger = logging.getLogger(__name__)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="reset")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--semantic", action="store_true")
    scope.add_argument("--all", action="store_true")
    parser.add_argument("--database")
    args = parser.parse_args(argv)
    if args.all and not args.database:
        parser.error("--all requires --database")
    with pipeline_lease():
        if args.all:
            result = delete_all_data(args.database)
            logger.info("Removed database %s: %s", args.database, result)
            return 0
        deleted = delete_semantic_layer(args.database)
        logger.info("Deleted %d semantic rows; compiling again", deleted)
        return 0 if compile_all() else 1
