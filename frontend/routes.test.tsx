// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { cleanup, screen } from '@testing-library/react';
import { Route, Routes } from 'react-router';
import { afterEach, describe, expect, it } from 'vitest';

import { Permission } from '@/enums/auth';
import { ADMIN, EDITOR, READER, renderWithMe } from '@/test/renderWithMe';
import type { Me } from '@/types/auth';
import { RequireAdmin, RequirePermission } from './routes';

const renderAt = (path: string, me: Me) =>
	renderWithMe(
		<Routes>
			<Route path="/" element={<p>home</p>} />
			<Route
				path="/settings"
				element={
					<RequireAdmin>
						<p>settings</p>
					</RequireAdmin>
				}
			/>
			<Route
				path="/chat"
				element={
					<RequirePermission permission={Permission.ChatUse}>
						<p>chat</p>
					</RequirePermission>
				}
			/>
		</Routes>,
		me,
		path,
	);

afterEach(cleanup);

describe('route guards', () => {
	it('lets an admin into settings', () => {
		renderAt('/settings', ADMIN);
		expect(screen.getByText('settings')).toBeTruthy();
	});

	it('sends an editor away from settings', () => {
		renderAt('/settings', EDITOR);
		expect(screen.getByText('home')).toBeTruthy();
	});

	it('lets an editor chat', () => {
		renderAt('/chat', EDITOR);
		expect(screen.getByText('chat')).toBeTruthy();
	});

	it('sends a reader away from chat', () => {
		renderAt('/chat', READER);
		expect(screen.queryByText('chat')).toBeNull();
		expect(screen.getByText('home')).toBeTruthy();
	});
});
