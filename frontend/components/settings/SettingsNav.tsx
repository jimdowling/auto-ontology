// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { Link, useLocation } from 'react-router';

type NavItem = { label: string; href: string };

const NAV_ITEMS: NavItem[] = [
	{ label: 'Sources', href: '/settings/sources' },
	{ label: 'Tags', href: '/settings/tags' },
	{ label: 'Rules', href: '/settings/rules' },
	{ label: 'PII Settings', href: '/settings/pii' },
	{ label: 'Semantic Input', href: '/settings/semantic-input' },
	{ label: 'Semantic Compilation', href: '/settings/semantic-compilation' },
	{ label: 'Agent Settings', href: '/settings/agent-settings' },
	{ label: 'Import / Export', href: '/settings/import-export' },
];

function rowClassName(selected: boolean) {
	return `flex min-h-9 items-center rounded-lg px-3 text-sm no-underline transition-colors ${
		selected
			? 'bg-accent/15 font-medium text-heading shadow-sm ring-1 ring-accent/30 dark:text-zinc-100'
			: 'text-heading hover:bg-zinc-100/90 dark:text-zinc-200 dark:hover:bg-zinc-800/70'
	}`;
}

export const SettingsNav = () => {
	const { pathname } = useLocation();

	return (
		<nav
			className="flex min-h-0 flex-1 flex-col gap-y-1 overflow-y-auto px-3 py-2 sm:px-4"
			aria-label="Settings sections"
		>
			{NAV_ITEMS.map((item) => {
				const selected = pathname === item.href || pathname.startsWith(`${item.href}/`);
				return (
					<Link key={item.href} to={item.href} className={rowClassName(selected)}>
						{item.label}
					</Link>
				);
			})}
		</nav>
	);
};
