// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Default and bounds of the SQL Query Timeout setting (Settings > Agent
 * Settings). They mirror `DEFAULT_`/`MIN_`/`MAX_SQL_QUERY_TIMEOUT_SECONDS` in
 * `auto_ontology/infra/feature_flags.py`, which reads the stored value before
 * every statement the text-to-SQL agent issues.
 */

export const DEFAULT_SQL_QUERY_TIMEOUT_SECONDS = 30;
export const MIN_SQL_QUERY_TIMEOUT_SECONDS = 1;
export const MAX_SQL_QUERY_TIMEOUT_SECONDS = 3600;

export function isValidSqlQueryTimeout(seconds: number): boolean {
	return (
		Number.isInteger(seconds) &&
		seconds >= MIN_SQL_QUERY_TIMEOUT_SECONDS &&
		seconds <= MAX_SQL_QUERY_TIMEOUT_SECONDS
	);
}
