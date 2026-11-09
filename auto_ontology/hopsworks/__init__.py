# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Hopsworks integration: config, identity, data sources, feature group vectors.

Everything that imports the ``hopsworks`` client lives in this package and
imports it lazily, so the rest of Auto Ontology runs and tests without it.
"""
