// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

type SpinnerProps = {
	className?: string;
	/** Announces the spinner as a status; without it the spinner is decorative. */
	'aria-label'?: string;
};

export const Spinner = ({ className = 'h-5 w-5', 'aria-label': ariaLabel }: SpinnerProps) => (
	<svg
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		strokeWidth={2}
		strokeLinecap="round"
		strokeLinejoin="round"
		role={ariaLabel ? 'status' : undefined}
		aria-label={ariaLabel}
		aria-hidden={ariaLabel ? undefined : true}
		className={`animate-spin ${className}`}
	>
		<circle cx="12" cy="12" r="10" opacity="0.25" />
		<path d="M22 12a10 10 0 0 0-10-10" />
	</svg>
);
