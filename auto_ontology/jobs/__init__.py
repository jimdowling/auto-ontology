# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The ontology's pipeline steps, each run as a Hopsworks Python job.

``ingest`` reads the sources into the catalog, ``compile`` builds the semantic
layer, ``embed`` reconciles both vector collections with the store, ``reset``
removes a layer, and ``import_model`` loads a model export. Each module's
``main(argv) -> int`` runs after :func:`auto_ontology.hopsworks.launch.bootstrap`
and returns the process exit code. Every step holds the pipeline lease
(:mod:`auto_ontology.jobs.runtime`) for its whole run.
"""
