// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { Suspense, useEffect } from 'react';
import { Outlet } from 'react-router';
import { useQueryClient } from '@tanstack/react-query';

import { AppTopBar } from '@/common/AppTopBar';
import { EmptyState } from '@/common/EmptyState';
import { Icon, IconName } from '@/common/icons';
import { NavRail } from '@/common/NavRail';
import { Spinner } from '@/common/Spinner';
import { BreadcrumbProvider } from '@/contexts/BreadcrumbContext';
import { EmptyStateVariant } from '@/enums/emptyState';
import { useMe } from '@/hooks/useMe';
import { tagQueries } from '@/lib/queries/tags';

const CenteredSpinner = ({ label }: { label: string }) => (
	<div className="flex h-full flex-1 items-center justify-center">
		<Spinner aria-label={label} className="h-8 w-8 text-secondary" />
	</div>
);

/**
 * Top bar, nav rail and the current page. Nothing renders until `api/me`
 * answers, so every page can rely on the caller's role being known.
 */
export const AppShell = () => {
	const queryClient = useQueryClient();
	const { me, error } = useMe();

	useEffect(() => {
		// Every picker reads the tag vocabulary; start it with the shell, not the first picker.
		if (me != null) void queryClient.prefetchQuery(tagQueries.vocabulary());
	}, [me, queryClient]);

	if (error != null) {
		return (
			<div className="flex h-full items-center justify-center p-6">
				<EmptyState
					variant={EmptyStateVariant.Welcome}
					illustration={<Icon name={IconName.Logo} className="h-10 w-10 text-accent" />}
					title="No access to this ontology"
					description={error.message}
				/>
			</div>
		);
	}
	if (me == null) return <CenteredSpinner label="Loading" />;

	return (
		<BreadcrumbProvider>
			<AppTopBar />
			<div className="flex min-h-0 flex-1">
				<NavRail />
				<div className="min-w-0 flex-1">
					<Suspense fallback={<CenteredSpinner label="Loading page" />}>
						<Outlet />
					</Suspense>
				</div>
			</div>
		</BreadcrumbProvider>
	);
};
