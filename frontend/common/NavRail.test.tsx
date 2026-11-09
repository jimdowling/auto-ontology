// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { cleanup, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ADMIN, EDITOR, READER, renderWithMe } from '@/test/renderWithMe';
import { NavRail } from './NavRail';

const visibleLinks = () =>
	screen.getAllByRole('link').map((link) => link.getAttribute('title') ?? link.textContent);

afterEach(cleanup);

describe('NavRail', () => {
	it('shows an admin every section', () => {
		renderWithMe(<NavRail />, ADMIN);
		expect(visibleLinks()).toEqual([
			'Chat',
			'Discovery',
			'Terms',
			'Analysis',
			'Exploration',
			'Data',
			'Analytics',
			'Settings',
		]);
	});

	it('hides Analytics and Settings from an editor', () => {
		renderWithMe(<NavRail />, EDITOR);
		expect(visibleLinks()).not.toContain('Analytics');
		expect(visibleLinks()).not.toContain('Settings');
		expect(visibleLinks()).toContain('Chat');
	});

	it('gives a reader no chat', () => {
		renderWithMe(<NavRail />, READER);
		expect(visibleLinks()).toEqual(['Discovery', 'Terms', 'Analysis', 'Exploration', 'Data']);
	});
});
