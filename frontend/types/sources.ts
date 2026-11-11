// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/** A Hopsworks data source the ontology ingests, as `ontology.yaml` lists it. */
export type Source = {
	/** The project data source's name. It must use SHARED credentials. */
	name: string;
	/** Schemas to ingest; null or empty ingests every schema. */
	schemas: string[] | null;
	/** Tables to ingest, as a regular expression; null ingests every table. */
	table_regex: string | null;
};
