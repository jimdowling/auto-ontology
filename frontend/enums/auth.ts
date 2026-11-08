// SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
// All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/** The caller's project role as `GET api/me` reports it. */
export enum Role {
	/** Data owner. */
	Admin = 'admin',
	/** Data scientist. */
	Editor = 'editor',
	/** Observer or feature store restricted: read-only, no chat. */
	Reader = 'reader',
}

/** The `resource:action` grants the UI gates on. */
export enum Permission {
	ChatUse = 'chat:use',
	CatalogEdit = 'catalog:edit',
	AnalysisManage = 'analysis:manage',
	ConversationDelete = 'conversation:delete',
}
