// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Pagination, pageWindow } from './Pagination';

afterEach(cleanup);

describe('pageWindow', () => {
	it('lists every page when there are few', () => {
		expect(pageWindow(1, 4)).toEqual([1, 2, 3, 4]);
	});

	it('elides the runs away from the current page', () => {
		expect(pageWindow(6, 12)).toEqual([1, 'ellipsis', 5, 6, 7, 'ellipsis', 12]);
	});

	it('shows a single skipped page instead of an ellipsis', () => {
		expect(pageWindow(3, 6)).toEqual([1, 2, 3, 4, 5, 6]);
	});
});

describe('Pagination', () => {
	it('reports the range and moves between pages', () => {
		const onPageChange = vi.fn();
		render(<Pagination page={2} pageSize={10} totalItems={25} onPageChange={onPageChange} />);

		expect(screen.getByText('11-20 out of 25')).toBeTruthy();
		expect(screen.getByRole('button', { name: '2' }).getAttribute('aria-current')).toBe('page');

		fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
		expect(onPageChange).toHaveBeenLastCalledWith(3);
		fireEvent.click(screen.getByRole('button', { name: '1' }));
		expect(onPageChange).toHaveBeenLastCalledWith(1);
	});

	it('disables the arrows at either end', () => {
		render(<Pagination page={1} pageSize={10} totalItems={5} onPageChange={() => {}} />);
		expect(
			(screen.getByRole('button', { name: 'Previous page' }) as HTMLButtonElement).disabled,
		).toBe(true);
		expect(
			(screen.getByRole('button', { name: 'Next page' }) as HTMLButtonElement).disabled,
		).toBe(true);
	});
});
