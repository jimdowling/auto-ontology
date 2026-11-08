// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { Icon, IconName } from '@/common/icons';
import type { TablePagination, TableRangeMeta } from '@/types/table';

const ELLIPSIS = 'ellipsis';

/**
 * Page numbers to show: the first, the last, and a window around `page`, with
 * an ellipsis wherever a run of pages is left out.
 */
export const pageWindow = (
	page: number,
	pageCount: number,
	siblings = 1,
): (number | typeof ELLIPSIS)[] => {
	const shown = new Set<number>([1, pageCount]);
	for (let p = page - siblings; p <= page + siblings; p++) {
		if (p >= 1 && p <= pageCount) shown.add(p);
	}
	const sorted = [...shown].sort((a, b) => a - b);
	const items: (number | typeof ELLIPSIS)[] = [];
	sorted.forEach((p, i) => {
		const previous = sorted[i - 1];
		if (previous != null && p - previous === 2) items.push(previous + 1);
		else if (previous != null && p - previous > 2) items.push(ELLIPSIS);
		items.push(p);
	});
	return items;
};

const defaultRangeText = ({ firstItemIndex, lastItemIndex, totalItems }: TableRangeMeta) =>
	`${firstItemIndex}-${lastItemIndex} out of ${totalItems}`;

const BUTTON_CLASS =
	'inline-flex h-8 min-w-8 items-center justify-center rounded-md px-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-30';

export const Pagination = ({
	page,
	pageSize,
	totalItems,
	onPageChange,
	rangeTextFormatFn = defaultRangeText,
	className,
}: TablePagination & { className?: string }) => {
	const pageCount = Math.max(1, Math.ceil(totalItems / pageSize));
	const current = Math.min(Math.max(page, 1), pageCount);
	const firstItemIndex = totalItems === 0 ? 0 : (current - 1) * pageSize + 1;
	const lastItemIndex = Math.min(current * pageSize, totalItems);

	return (
		<nav
			aria-label="Pagination"
			className={`flex items-center gap-3 text-sm text-body dark:text-zinc-400 ${className ?? ''}`}
		>
			<div className="flex items-center gap-1">
				<button
					type="button"
					aria-label="Previous page"
					disabled={current <= 1}
					onClick={() => onPageChange(current - 1)}
					className={`${BUTTON_CLASS} hover:bg-zinc-100 dark:hover:bg-zinc-800`}
				>
					<Icon name={IconName.ChevronRight} className="h-4 w-4 rotate-180" />
				</button>
				{pageWindow(current, pageCount).map((item, index) =>
					item === ELLIPSIS ? (
						<span key={`ellipsis-${index}`} className="px-1 text-secondary">
							…
						</span>
					) : (
						<button
							key={item}
							type="button"
							aria-current={item === current ? 'page' : undefined}
							onClick={() => onPageChange(item)}
							className={`${BUTTON_CLASS} ${
								item === current
									? 'bg-accent/15 text-accent-deep dark:text-accent-soft'
									: 'hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800'
							}`}
						>
							{item}
						</button>
					),
				)}
				<button
					type="button"
					aria-label="Next page"
					disabled={current >= pageCount}
					onClick={() => onPageChange(current + 1)}
					className={`${BUTTON_CLASS} hover:bg-zinc-100 dark:hover:bg-zinc-800`}
				>
					<Icon name={IconName.ChevronRight} className="h-4 w-4" />
				</button>
			</div>
			<span className="whitespace-nowrap">
				{rangeTextFormatFn({ firstItemIndex, lastItemIndex, totalItems })}
			</span>
		</nav>
	);
};
