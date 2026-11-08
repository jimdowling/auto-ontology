// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { queryOptions, useQuery } from '@tanstack/react-query';

import { meApi } from '@/api/me';
import { Permission, Role } from '@/enums/auth';
import type { Me } from '@/types/auth';

export const meQuery = () =>
	queryOptions({
		queryKey: ['me'],
		queryFn: async (): Promise<Me> => {
			const res = await meApi.get();
			if (res.error) throw new Error(res.message ?? 'Failed to load your role.');
			return res;
		},
		// The backend caches project roles for a minute; a role change shows up on reload.
		staleTime: Infinity,
		retry: false,
	});

/** Admins hold every permission, whatever list the backend sends. */
export const hasPermission = (me: Me | undefined, permission: Permission): boolean =>
	me != null && (me.role === Role.Admin || me.permissions.includes(permission));

/**
 * The caller's identity and role. `can` and `isAdmin` answer false until it
 * has loaded; the app shell renders no page before then.
 */
export const useMe = () => {
	const { data: me, error, isPending } = useQuery(meQuery());
	return {
		me,
		error,
		isPending,
		isAdmin: me?.role === Role.Admin,
		can: (permission: Permission) => hasPermission(me, permission),
	};
};
