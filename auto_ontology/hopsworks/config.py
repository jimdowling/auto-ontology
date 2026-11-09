# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""``ontology.yaml``: one ontology system's configuration.

The ontology factory writes the file next to the app's launcher; its shape is
the contract in HWORKS-3744_api.md section 3. :func:`load` finds it, validates
it and caches it for the process.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

_HOPSFS_MOUNT = Path("/hopsfs")


@dataclass(frozen=True)
class Source:
    name: str
    schemas: tuple[str, ...] = ()
    table_regex: str | None = None


@dataclass(frozen=True)
class ModelConfig:
    mode: str
    deployment: str | None = None
    model: str | None = None


@dataclass(frozen=True)
class EmbeddingConfig(ModelConfig):
    dimension: int = 2048
    request: str = "v1-prefix"


@dataclass(frozen=True)
class OntologyConfig:
    name: str
    app: str
    feature_store: str | None
    data_objects_fg: str
    semantic_fg: str
    fg_version: int
    embedding: EmbeddingConfig
    llm: ModelConfig
    sources: tuple[Source, ...] = ()
    jobs: dict[str, str] = field(default_factory=dict)
    pii_detection: bool = False
    distinct_value_probing: bool = True


class ConfigError(ValueError):
    """``ontology.yaml`` is missing, unreadable or does not match the contract."""


def _resolve(path: str) -> Path | None:
    candidate = Path(path)
    if candidate.is_file():
        return candidate
    if not candidate.is_absolute():
        mounted = _HOPSFS_MOUNT / candidate
        if mounted.is_file():
            return mounted
    return None


def _download(path: str) -> Path:
    from auto_ontology.hopsworks.client import login

    project = login()
    target = Path(os.environ.get("TMPDIR", "/tmp")) / "ontology-config"
    target.mkdir(parents=True, exist_ok=True)
    local = project.get_dataset_api().download(path, str(target), overwrite=True)
    return Path(local)


def config_path() -> str:
    """Where the config lives: ``--config`` (via ``ONTOLOGY_CONFIG``) or ``./ontology.yaml``."""
    return os.environ.get("ONTOLOGY_CONFIG", "ontology.yaml")


def parse(document: dict[str, Any]) -> OntologyConfig:
    """Validate a loaded ``ontology.yaml``. Raises :class:`ConfigError` on any mismatch."""
    try:
        if document.get("schema_version") != 1:
            raise ConfigError(
                f"unsupported schema_version {document.get('schema_version')!r}"
            )
        groups = document["feature_groups"]
        embedding = document["embedding"]
        llm = document["llm"]
        if embedding["mode"] not in ("local", "external"):
            raise ConfigError(
                f"embedding.mode must be local or external, not {embedding['mode']!r}"
            )
        if llm["mode"] not in ("local", "external"):
            raise ConfigError(
                f"llm.mode must be local or external, not {llm['mode']!r}"
            )
        if embedding.get("request", "v1-prefix") not in ("v1-prefix", "v2-embed"):
            raise ConfigError(
                f"embedding.request {embedding['request']!r} is not v1-prefix or v2-embed"
            )
        return OntologyConfig(
            name=document["name"],
            app=document["app"],
            feature_store=document.get("feature_store"),
            data_objects_fg=groups["data_objects"],
            semantic_fg=groups["semantic"],
            fg_version=int(groups.get("version", 1)),
            embedding=EmbeddingConfig(
                mode=embedding["mode"],
                deployment=embedding.get("deployment"),
                model=embedding.get("model"),
                dimension=int(embedding.get("dimension", 2048)),
                request=embedding.get("request", "v1-prefix"),
            ),
            llm=ModelConfig(
                mode=llm["mode"],
                deployment=llm.get("deployment"),
                model=llm.get("model"),
            ),
            sources=tuple(
                Source(
                    name=source["name"],
                    schemas=tuple(source.get("schemas") or ()),
                    table_regex=source.get("table_regex"),
                )
                for source in document.get("sources") or ()
            ),
            jobs=dict(document.get("jobs") or {}),
            pii_detection=bool(document.get("pii_detection", False)),
            distinct_value_probing=bool(document.get("distinct_value_probing", True)),
        )
    except KeyError as missing:
        raise ConfigError(f"ontology.yaml is missing {missing}") from None


@cache
def load() -> OntologyConfig:
    """The process's config. Raises :class:`ConfigError` when it cannot be found or parsed."""
    path = config_path()
    local = _resolve(path)
    if local is None:
        try:
            local = _download(path)
        except Exception as exc:
            raise ConfigError(
                f"cannot find {path} locally, under /hopsfs, or through the dataset API: {exc}"
            ) from exc
    try:
        document = yaml.safe_load(local.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read {local}: {exc}") from exc
    if not isinstance(document, dict):
        raise ConfigError(f"{local} does not hold a mapping")
    return parse(document)
