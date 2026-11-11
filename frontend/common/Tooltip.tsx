// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

const OPEN_DELAY_MS = 400;
// Long enough to move the pointer from the trigger onto the tooltip, which can scroll.
const CLOSE_DELAY_MS = 100;
const GAP_PX = 4;

type Placement = { left: number; top?: number; bottom?: number };

const placeBelowOrAbove = (rect: DOMRect): Placement =>
	rect.bottom > window.innerHeight * 0.6
		? { left: rect.left, bottom: window.innerHeight - rect.top + GAP_PX }
		: { left: rect.left, top: rect.bottom + GAP_PX };

type TooltipProps = {
	content: ReactNode;
	/** Classes for the floating panel. */
	className?: string;
	children: ReactNode;
};

/**
 * Shows `content` under the wrapped element on hover or keyboard focus,
 * aligned to its start edge, or above it near the bottom of the viewport.
 */
export const Tooltip = ({ content, className, children }: TooltipProps) => {
	const id = useId();
	const triggerRef = useRef<HTMLSpanElement | null>(null);
	const timer = useRef<number | undefined>(undefined);
	const [placement, setPlacement] = useState<Placement | null>(null);

	const schedule = useCallback((fn: () => void, delay: number) => {
		window.clearTimeout(timer.current);
		timer.current = window.setTimeout(fn, delay);
	}, []);

	const open = useCallback(() => {
		schedule(() => {
			const target = triggerRef.current?.firstElementChild;
			if (target != null) setPlacement(placeBelowOrAbove(target.getBoundingClientRect()));
		}, OPEN_DELAY_MS);
	}, [schedule]);

	const close = useCallback(() => schedule(() => setPlacement(null), CLOSE_DELAY_MS), [schedule]);
	const keepOpen = useCallback(() => window.clearTimeout(timer.current), []);

	useEffect(() => () => window.clearTimeout(timer.current), []);

	useEffect(() => {
		if (placement == null) return;
		const dismiss = () => setPlacement(null);
		const onKey = (event: KeyboardEvent) => {
			if (event.key === 'Escape') dismiss();
		};
		window.addEventListener('scroll', dismiss, true);
		window.addEventListener('keydown', onKey);
		return () => {
			window.removeEventListener('scroll', dismiss, true);
			window.removeEventListener('keydown', onKey);
		};
	}, [placement]);

	return (
		<>
			<span
				ref={triggerRef}
				className="contents"
				onPointerEnter={open}
				onPointerLeave={close}
				onFocus={open}
				onBlur={close}
				aria-describedby={placement == null ? undefined : id}
			>
				{children}
			</span>
			{placement != null &&
				createPortal(
					<div
						id={id}
						role="tooltip"
						onPointerEnter={keepOpen}
						onPointerLeave={close}
						className={`fixed ${className ?? ''}`}
						style={placement}
					>
						{content}
					</div>,
					document.body,
				)}
		</>
	);
};
