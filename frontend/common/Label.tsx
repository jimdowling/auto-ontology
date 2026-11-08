// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { Text } from '@/common/Text';

// A label carries a name, so it is capped and clipped rather than allowed to
// grow: one oversized value (a description that ended up in a name field, say)
// would otherwise take over the whole chip list.
const LABEL_BASE =
	'inline-flex min-w-0 max-w-[min(24rem,100%)] items-center overflow-hidden rounded-full border px-3 py-1 text-xs font-medium';
const LABEL_GREEN =
	'border-accent/40 bg-accent/10 text-accent-deep dark:border-accent/30 dark:bg-accent/15 dark:text-accent-soft';
const LABEL_GREEN_HOVER =
	'hover:border-accent/70 hover:bg-accent/20 hover:text-accent-deep dark:hover:border-accent/60 dark:hover:bg-accent/25 dark:hover:text-accent-soft';

type LabelStyleProps = {
	label: string;
};

/**
 * A label is clickable, removable, or neither — never both.
 *
 * Spelled as a union so the pair is a type error rather than a silent one: the
 * two together would be a button containing a button, which is invalid markup
 * and leaves the targets indistinguishable to a screen reader.
 */
export type LabelProps = LabelStyleProps &
	(
		| {
				/** Makes the whole label a button; otherwise it is read-only. */
				onClick?: () => void;
				onRemove?: never;
		  }
		| {
				onClick?: never;
				/** Adds a trailing × that calls this. */
				onRemove?: () => void;
		  }
	);

export const Label = ({ label, onClick, onRemove }: LabelProps) => {
	const interactive = onClick != null;
	const className = [
		LABEL_BASE,
		LABEL_GREEN,
		interactive ? `cursor-pointer transition-colors ${LABEL_GREEN_HOVER}` : '',
	]
		.filter(Boolean)
		.join(' ');
	// Clipping is what makes the cap above win over a long value, and a clipped
	// chip reveals itself in the same tooltip the tags elsewhere use.
	const content = <Text text={label} />;

	if (interactive) {
		return (
			<button type="button" onClick={onClick} className={className}>
				{content}
			</button>
		);
	}
	return (
		<span className={className}>
			{content}
			{onRemove != null && (
				<button
					type="button"
					onClick={onRemove}
					aria-label={`Remove ${label}`}
					title={`Remove ${label}`}
					className="-mr-1 ml-1.5 flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center rounded-full transition-colors hover:bg-black/10 dark:hover:bg-white/15"
				>
					<svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden>
						<path
							d="M1.5 1.5L8.5 8.5M8.5 1.5L1.5 8.5"
							stroke="currentColor"
							strokeWidth="1.5"
							strokeLinecap="round"
						/>
					</svg>
				</button>
			)}
		</span>
	);
};
