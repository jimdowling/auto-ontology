// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { lazy, type ReactNode } from 'react';
import { createHashRouter, Navigate, useSearchParams } from 'react-router';

import { AppShell } from '@/components/AppShell';
import { SettingsPanelLayout } from '@/components/settings/SettingsPanelLayout';
import { Permission } from '@/enums/auth';
import { useMe } from '@/hooks/useMe';

const ChatView = lazy(() =>
	import('@/components/chatPage/ChatView').then((m) => ({ default: m.ChatView })),
);
const DiscoveryView = lazy(() =>
	import('@/components/discoveryPage/DiscoveryView').then((m) => ({ default: m.DiscoveryView })),
);
const TermsView = lazy(() =>
	import('@/components/termsPage/TermsView').then((m) => ({ default: m.TermsView })),
);
const AnalysisView = lazy(() =>
	import('@/components/analysisPage/AnalysisView').then((m) => ({ default: m.AnalysisView })),
);
const ExplorationView = lazy(() =>
	import('@/components/explorationPage/ExplorationView').then((m) => ({
		default: m.ExplorationView,
	})),
);
const DataWorkspaceView = lazy(() =>
	import('@/components/dataPage/DataWorkspaceView').then((m) => ({
		default: m.DataWorkspaceView,
	})),
);
const AnalyticsView = lazy(() =>
	import('@/components/analyticsPage/AnalyticsView').then((m) => ({ default: m.AnalyticsView })),
);
const TagsSettingsView = lazy(() =>
	import('@/pages/settings/tags/TagsSettingsView').then((m) => ({
		default: m.TagsSettingsView,
	})),
);
const RulesSettingsPage = lazy(() =>
	import('@/pages/settings/rules/RulesSettingsPage').then((m) => ({
		default: m.RulesSettingsPage,
	})),
);
const PiiSettingsPage = lazy(() =>
	import('@/pages/settings/pii/PiiSettingsPage').then((m) => ({ default: m.PiiSettingsPage })),
);
const SemanticInputPage = lazy(() =>
	import('@/pages/settings/semantic-input/SemanticInputPage').then((m) => ({
		default: m.SemanticInputPage,
	})),
);
const SemanticCompilationPage = lazy(() =>
	import('@/pages/settings/semantic-compilation/SemanticCompilationPage').then((m) => ({
		default: m.SemanticCompilationPage,
	})),
);
const AgentSettingsPage = lazy(() =>
	import('@/pages/settings/agent-settings/AgentSettingsPage').then((m) => ({
		default: m.AgentSettingsPage,
	})),
);
const ImportExportPage = lazy(() =>
	import('@/pages/settings/import-export/ImportExportPage').then((m) => ({
		default: m.ImportExportPage,
	})),
);

/** Readers have no chat, so they land on Discovery. */
const HomeRedirect = () => {
	const { can } = useMe();
	return <Navigate to={can(Permission.ChatUse) ? '/chat' : '/discovery'} replace />;
};

export const RequireAdmin = ({ children }: { children: ReactNode }) => {
	const { isAdmin } = useMe();
	return isAdmin ? children : <Navigate to="/" replace />;
};

export const RequirePermission = ({
	permission,
	children,
}: {
	permission: Permission;
	children: ReactNode;
}) => {
	const { can } = useMe();
	return can(permission) ? children : <Navigate to="/" replace />;
};

/**
 * `?q=` is how the top bar's search dialog hands a search over. `?n=` is a
 * one-off token per hand-over, so handing over the term already on screen is
 * still a navigation the view can tell apart.
 */
const DiscoveryPage = () => {
	const [searchParams] = useSearchParams();
	return (
		<DiscoveryView
			initialQuery={searchParams.get('q') ?? ''}
			handoverId={searchParams.get('n') ?? ''}
		/>
	);
};

export const router = createHashRouter([
	{
		element: <AppShell />,
		children: [
			{ index: true, element: <HomeRedirect /> },
			{
				path: 'chat',
				element: (
					<RequirePermission permission={Permission.ChatUse}>
						<ChatView />
					</RequirePermission>
				),
			},
			{ path: 'discovery', element: <DiscoveryPage /> },
			{ path: 'terms', element: <TermsView /> },
			{ path: 'analysis', element: <AnalysisView /> },
			{ path: 'exploration', element: <ExplorationView /> },
			{ path: 'data', element: <DataWorkspaceView /> },
			{
				path: 'analytics',
				element: (
					<RequireAdmin>
						<AnalyticsView />
					</RequireAdmin>
				),
			},
			{
				path: 'settings',
				element: (
					<RequireAdmin>
						<SettingsPanelLayout />
					</RequireAdmin>
				),
				children: [
					{ index: true, element: <Navigate to="tags" replace /> },
					{ path: 'tags', element: <TagsSettingsView /> },
					{ path: 'rules', element: <RulesSettingsPage /> },
					{ path: 'pii', element: <PiiSettingsPage /> },
					{ path: 'semantic-input', element: <SemanticInputPage /> },
					{ path: 'semantic-compilation', element: <SemanticCompilationPage /> },
					{ path: 'agent-settings', element: <AgentSettingsPage /> },
					{ path: 'import-export', element: <ImportExportPage /> },
				],
			},
			{ path: '*', element: <Navigate to="/" replace /> },
		],
	},
]);
