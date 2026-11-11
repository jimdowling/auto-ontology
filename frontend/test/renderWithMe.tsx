// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

import { meQuery } from '@/hooks/useMe';
import { Permission, Role } from '@/enums/auth';
import type { Me } from '@/types/auth';

export const ADMIN: Me = { username: 'owner', role: Role.Admin, permissions: [] };
export const EDITOR: Me = {
	username: 'scientist',
	role: Role.Editor,
	permissions: [
		Permission.ChatUse,
		Permission.CatalogEdit,
		Permission.AnalysisManage,
		'catalog:read',
		'tag:read',
	],
};
export const READER: Me = {
	username: 'observer',
	role: Role.Reader,
	permissions: ['catalog:read', 'tag:read'],
};

/** Renders `ui` under a router at `path`, with `api/me` already answered as `me`. */
export const renderWithMe = (ui: ReactElement, me: Me, path = '/') => {
	const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
	queryClient.setQueryData(meQuery().queryKey, me);
	return render(
		<QueryClientProvider client={queryClient}>
			<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
		</QueryClientProvider>,
	);
};
