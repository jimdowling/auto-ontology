# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Arguments for the pipeline job runs the app starts."""

from __future__ import annotations

from types import SimpleNamespace

from auto_ontology.hopsworks.jobs import run_arguments

JOB = SimpleNamespace(config={"defaultArgs": "--config Resources/sales/ontology.yaml"})


def test_a_run_without_arguments_uses_the_job_defaults() -> None:
    assert run_arguments(JOB, None) is None


def test_extra_arguments_keep_the_config_default() -> None:
    assert (
        run_arguments(JOB, "--source sales_mysql")
        == "--config Resources/sales/ontology.yaml --source sales_mysql"
    )


def test_a_job_without_defaults_gets_the_arguments_alone() -> None:
    assert run_arguments(SimpleNamespace(config={}), "--semantic") == "--semantic"
