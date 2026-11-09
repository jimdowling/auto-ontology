// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { cleanup, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { sourcesApi } from '@/api/sources';
import { ADMIN, EDITOR, renderWithMe } from '@/test/renderWithMe';
import type { Source } from '@/types/sources';
import { SourcesSettingsPage, parseSchemas } from './SourcesSettingsPage';

const SOURCES: Source[] = [
	{ name: 'sales_mysql', schemas: ['sales', 'crm'], table_regex: null },
	{ name: 'events_pg', schemas: null, table_regex: '^fact_' },
];

afterEach(() => {
	cleanup();
	vi.restoreAllMocks();
});

describe('parseSchemas', () => {
	it('trims and drops empty entries', () => {
		expect(parseSchemas(' sales, ,crm ')).toEqual(['sales', 'crm']);
	});

	it('reads an empty list as every schema', () => {
		expect(parseSchemas(' , ')).toBeNull();
	});
});

describe('SourcesSettingsPage', () => {
	it('lists the sources and lets an admin change them', async () => {
		vi.spyOn(sourcesApi, 'list').mockResolvedValue(SOURCES);
		renderWithMe(<SourcesSettingsPage />, ADMIN);

		expect(await screen.findByText('sales_mysql')).toBeTruthy();
		expect(screen.getByText('sales, crm')).toBeTruthy();
		expect(screen.getByText('All schemas')).toBeTruthy();
		expect(screen.getByText('^fact_')).toBeTruthy();
		expect(screen.getAllByRole('button', { name: 'Remove' })).toHaveLength(2);
		expect(screen.getByRole('button', { name: 'Add Source' })).toBeTruthy();
	});

	it('is read-only for anyone else', async () => {
		vi.spyOn(sourcesApi, 'list').mockResolvedValue(SOURCES);
		renderWithMe(<SourcesSettingsPage />, EDITOR);

		expect(await screen.findByText('sales_mysql')).toBeTruthy();
		expect(screen.queryByRole('button', { name: 'Remove' })).toBeNull();
		expect(screen.queryByRole('button', { name: 'Add Source' })).toBeNull();
	});
});
