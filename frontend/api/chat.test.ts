// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';

import { streamChat } from './chat';

const sseResponse = (chunks: string[]) => {
	const encoder = new TextEncoder();
	const body = new ReadableStream<Uint8Array>({
		start(controller) {
			chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
			controller.close();
		},
	});
	return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
};

const callbacks = () => ({
	onStart: vi.fn(),
	onStep: vi.fn(),
	onSql: vi.fn(),
	onResult: vi.fn(),
	onCharts: vi.fn(),
	onError: vi.fn(),
	onDone: vi.fn(),
});

afterEach(() => {
	vi.restoreAllMocks();
});

describe('streamChat', () => {
	it('posts to a relative api URL and dispatches events split across chunks', async () => {
		const fetchMock = vi
			.spyOn(globalThis, 'fetch')
			.mockResolvedValue(
				sseResponse([
					'data: {"type":"step","message":"thinking"}\n',
					'data: {"type":"sql","sql":"SELECT 1"}\ndata: {"type":"res',
					'ult","answer":"one"}\n\ndata: [DONE]\n',
				]),
			);
		const cb = callbacks();

		streamChat({ question: 'how many?' }, cb);
		await vi.waitFor(() => expect(cb.onDone).toHaveBeenCalled());

		expect(fetchMock.mock.calls[0]?.[0]).toBe('api/chat/completions');
		expect(cb.onStart).toHaveBeenCalledOnce();
		expect(cb.onStep).toHaveBeenCalledWith({ type: 'step', message: 'thinking' });
		expect(cb.onSql).toHaveBeenCalledWith({ type: 'sql', sql: 'SELECT 1' });
		expect(cb.onResult).toHaveBeenCalledWith({ type: 'result', answer: 'one' });
		expect(cb.onError).not.toHaveBeenCalled();
	});

	it('reports a stream that closes before [DONE]', async () => {
		vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			sseResponse(['data: {"type":"step","message":"thinking"}\n']),
		);
		const cb = callbacks();

		streamChat({ question: 'how many?' }, cb);
		await vi.waitFor(() => expect(cb.onError).toHaveBeenCalled());

		expect(cb.onDone).not.toHaveBeenCalled();
	});

	it('surfaces the backend detail when the request is refused', async () => {
		vi.spyOn(globalThis, 'fetch').mockResolvedValue(
			new Response(JSON.stringify({ detail: 'Conversation in progress' }), { status: 409 }),
		);
		const cb = callbacks();

		streamChat({ question: 'how many?' }, cb);
		await vi.waitFor(() => expect(cb.onError).toHaveBeenCalled());

		expect(cb.onError).toHaveBeenCalledWith({
			type: 'error',
			message: 'Conversation in progress',
		});
		expect(cb.onStart).not.toHaveBeenCalled();
	});
});
