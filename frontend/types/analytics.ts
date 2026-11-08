// SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

export type ConversationAnalytics = {
	id: string;
	/** The Hopsworks user who asked. */
	username: string;
	source: string;
	question: string;
	question_timestamp: string;
	response: string | null;
	response_timestamp: string | null;
	sql: string | null;
};
