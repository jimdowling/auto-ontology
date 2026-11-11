# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The launchers, when a spawned worker process re-runs them."""

from __future__ import annotations

import multiprocessing

import pytest

from auto_ontology.hopsworks import launch


def test_a_spawned_child_neither_starts_the_app_nor_runs_a_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The chat worker is spawned, and spawn re-runs the system's app.py, which
    # calls app() at import; a second server there fails on the port.
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("bootstrap ran in a spawned child")

    monkeypatch.setattr(multiprocessing, "parent_process", lambda: object())
    monkeypatch.setattr(launch, "bootstrap", refuse)
    launch.app()
    launch.job("ingest")
