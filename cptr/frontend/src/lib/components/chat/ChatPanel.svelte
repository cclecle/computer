<script lang="ts">
	import { getChat, getChats, deleteChat as apiDeleteChat, sendMessage as apiSendMessage, approveToolCall, cancelTask, updateCurrentMessage, updateMessage, createMessage, type ChatMessageRow, type ChatInfo } from '$lib/apis/chat';
	import { chatModels, defaultModel, streamingChatTabs } from '$lib/stores/chat';
	import { socketStore } from '$lib/stores/socket.svelte';
	import { onMount, onDestroy, tick } from 'svelte';
	import { get } from 'svelte/store';
	import { currentWorkspace, autoApproveTools } from '$lib/stores';

	import ChatInput from './ChatInput.svelte';
	import UserMessage from './UserMessage.svelte';
	import AssistantMessage from './AssistantMessage.svelte';
	import ChatHistory from './ChatHistory.svelte';

	interface Props {
		workspace: string;
		chatId?: string;
		tabId?: string;
	}
	let { workspace, chatId: initialChatId, tabId }: Props = $props();

	let inputText = $state('');
	let chatId = $state<string | null>(initialChatId ?? null);
	let selectedModel = $state('');
	let allMessages = $state<ChatMessageRow[]>([]);
	let currentMessageId = $state<string | null>(null);
	let previousChats = $state<ChatInfo[]>([]);
	let messagesEl: HTMLDivElement;
	let chatInputEl: ChatInput;
	let sending = $state(false);
	let autoScroll = $state(true);

	// ── Tree-aware path computation ─────────────────────────────

	interface PathEntry {
		msg: ChatMessageRow;
		siblingIds: string[];
		siblingIndex: number;
	}

	function buildChildrenMap(msgs: ChatMessageRow[]): Map<string | null, ChatMessageRow[]> {
		const map = new Map<string | null, ChatMessageRow[]>();
		for (const m of msgs) {
			const key = m.parent_id ?? null;
			if (!map.has(key)) map.set(key, []);
			map.get(key)!.push(m);
		}
		return map;
	}

	function findLeaf(messageId: string, childrenMap: Map<string | null, ChatMessageRow[]>): string {
		let cur = messageId;
		while (true) {
			const children = childrenMap.get(cur);
			if (!children?.length) return cur;
			cur = children[children.length - 1].id; // follow latest child
		}
	}

	const activePath = $derived.by((): PathEntry[] => {
		if (!allMessages.length) return [];

		const msgMap = new Map(allMessages.map((m) => [m.id, m]));
		const childrenMap = buildChildrenMap(allMessages);

		// Determine effective currentId — fall back to last message if unset
		const effectiveId = currentMessageId && msgMap.has(currentMessageId)
			? currentMessageId
			: allMessages.length > 0 ? allMessages[allMessages.length - 1].id : null;

		if (!effectiveId) return [];

		// Walk up from effectiveId to root to find ancestor set
		const ancestorIds = new Set<string>();
		let cur: string | null = effectiveId;
		while (cur) {
			ancestorIds.add(cur);
			const msg = msgMap.get(cur);
			cur = msg?.parent_id ?? null;
		}

		// Walk down from root, at each level pick the child in ancestorIds
		const path: PathEntry[] = [];
		let parentId: string | null = null;
		while (true) {
			const siblings = childrenMap.get(parentId);
			if (!siblings?.length) break;
			const next = siblings.find((c) => ancestorIds.has(c.id)) || siblings[0];
			path.push({
				msg: next,
				siblingIds: siblings.map((s) => s.id),
				siblingIndex: siblings.findIndex((s) => s.id === next.id),
			});
			parentId = next.id;
		}

		return path;
	});

	const streaming = $derived(allMessages.some((m) => m.role === 'assistant' && !m.done));
	const isLanding = $derived(allMessages.length === 0 && !chatId);
	const workspaceName = $derived(workspace.split('/').pop() || 'workspace');

	// ── Load chat from DB ───────────────────────────────────────

	async function loadChat(id: string) {
		chatId = id;
		const data = await getChat(id);
		allMessages = data.messages;
		currentMessageId = data.chat.current_message_id;
	}

	async function loadPreviousChats() {
		try {
			const data = await getChats(workspace);
			previousChats = data.chats || [];
		} catch {
			previousChats = [];
		}
	}

	async function openChat(id: string) {
		await loadChat(id);
		const chat = previousChats.find((c) => c.id === id);
		if (tabId) updateTab(tabId, id, chat?.title || 'Chat');
	}

	async function deleteChat(id: string) {
		await apiDeleteChat(id);
		previousChats = previousChats.filter((c) => c.id !== id);
	}

	// ── Socket listener ─────────────────────────────────────────

	function handleSocketEvent(data: {
		chat_id: string;
		message_id: string;
		delta?: string;
		output?: any;
		done?: boolean;
	}) {
		if (data.chat_id !== chatId) return;
		const msg = allMessages.find((m) => m.id === data.message_id);
		if (!msg) return;

		if (data.delta) {
			msg.content += data.delta;
			allMessages = [...allMessages];
		}
		if (data.output) {
			// Merge by call_id to avoid duplicates and update status of existing items
			const existing = msg.output || [];
			const callId = data.output.call_id;
			const itemType = data.output.type;
			if (callId && itemType) {
				const existingIdx = existing.findIndex(
					(o: any) => o.type === itemType && o.call_id === callId
				);
				if (existingIdx >= 0) {
					// Update existing item in-place (e.g., pending → completed)
					existing[existingIdx] = { ...existing[existingIdx], ...data.output };
					msg.output = [...existing];
				} else {
					msg.output = [...existing, data.output];
				}
			} else {
				msg.output = [...existing, data.output];
			}
			allMessages = [...allMessages];
		}
		if (data.done) {
			loadChat(data.chat_id);
		}
	}

	function handleReconnect() {
		if (chatId) loadChat(chatId);
	}

	const MODEL_STORAGE_KEY = 'cptr:chat:lastModel';

	onMount(() => {
		const models = get(chatModels);
		const saved = localStorage.getItem(MODEL_STORAGE_KEY);
		const dm = get(defaultModel);
		if (saved && models.some((m) => m.id === saved)) selectedModel = saved;
		else if (dm) selectedModel = dm;
		else if (models.length) selectedModel = models[0].id;

		if (chatId) {
			loadChat(chatId);
		} else {
			loadPreviousChats();
		}

		const tryBind = () => {
			const socket = socketStore.getSocket();
			if (!socket) { setTimeout(tryBind, 100); return; }
			socket.on('events:chat', handleSocketEvent);
			socket.on('connect', handleReconnect);
		};
		tryBind();
	});

	onDestroy(() => {
		const socket = socketStore.getSocket();
		if (socket) {
			socket.off('events:chat', handleSocketEvent);
			socket.off('connect', handleReconnect);
		}
		// Clean up streaming indicator for this tab
		if (tabId) {
			streamingChatTabs.update((s) => { s.delete(tabId); return new Set(s); });
		}
	});

	// ── Persist model selection ─────────────────────────────────

	$effect(() => {
		if (selectedModel) localStorage.setItem(MODEL_STORAGE_KEY, selectedModel);
	});

	// ── Sync streaming state to shared store for tab icon ────

	$effect(() => {
		if (!tabId) return;
		const tid = tabId;
		streamingChatTabs.update((s) => {
			const next = new Set(s);
			if (streaming) next.add(tid); else next.delete(tid);
			return next;
		});
	});

	// ── Auto-scroll ─────────────────────────────────────────────

	function scrollToBottom() {
		if (!messagesEl) return;
		messagesEl.scrollTop = messagesEl.scrollHeight;
		// Follow-up scroll to account for content-visibility re-layouts
		requestAnimationFrame(() => {
			if (messagesEl) {
				messagesEl.scrollTop = messagesEl.scrollHeight;
			}
		});
	}

	function handleMessagesScroll() {
		if (!messagesEl) return;
		autoScroll =
			messagesEl.scrollHeight - messagesEl.scrollTop <= messagesEl.clientHeight + 50;
	}

	$effect(() => {
		if (activePath.length && messagesEl && autoScroll) {
			requestAnimationFrame(() => {
				scrollToBottom();
			});
		}
	});

	// ── Actions ─────────────────────────────────────────────────

	async function send() {
		const text = inputText.trim();
		if (!text || !selectedModel || sending) return;
		sending = true;
		inputText = '';
		autoScroll = true;
		await tick();
		chatInputEl?.resetHeight();

		// parent_id = last message in active path, or null for first message
		const lastMsg = activePath.length > 0 ? activePath[activePath.length - 1].msg : null;
		const parentId = lastMsg?.id ?? null;
		const isNew = !chatId;

		// ── Optimistic UI: add user message immediately ──────────
		const tempId = `temp-${Date.now()}`;
		const optimisticMsg: ChatMessageRow = {
			id: tempId,
			parent_id: parentId,
			role: 'user',
			content: text,
			model: selectedModel,
			done: true,
			output: null,
			usage: null,
			meta: null,
			created_at: Date.now() / 1000,
		};
		allMessages = [...allMessages, optimisticMsg];
		currentMessageId = tempId;

		// Update tab label instantly for new chats
		if (isNew && tabId) {
			updateTab(tabId, `pending-${tempId}`, text.slice(0, 40) || 'Chat');
		}

		try {
			const result = await apiSendMessage(text, selectedModel, workspace, chatId ?? undefined, parentId, { auto_approve_tools: get(autoApproveTools) });
			await loadChat(result.chat_id);
			if (isNew && tabId) {
				updateTab(tabId, result.chat_id, text.slice(0, 40) || 'Chat');
			}
		} catch (e) {
			console.error('[chat] send error', e);
			// Remove the optimistic message on failure
			allMessages = allMessages.filter((m) => m.id !== tempId);
			currentMessageId = parentId;
			throw e;
		} finally {
			sending = false;
			chatInputEl?.focus();
		}
	}

	async function handleCancel() {
		const active = allMessages.find((m) => m.role === 'assistant' && !m.done);
		if (!active || !chatId) return;

		// Optimistically mark as done so streaming indicator disappears immediately
		if (active.output) {
			for (const item of active.output) {
				if (item.type === 'function_call' && item.status === 'pending') {
					item.status = 'rejected';
				}
			}
		}
		active.done = true;
		allMessages = [...allMessages];

		try {
			await cancelTask(chatId, active.id);
		} catch (err) {
			console.error('[chat] cancel error', err);
		}
		// Reload to get canonical state from DB
		await loadChat(chatId);
	}

	function handleApprove(messageId: string, callId: string, approved: boolean) {
		if (!chatId) return;

		// Optimistically update local state so Allow/Deny buttons disappear immediately
		const msg = allMessages.find((m) => m.id === messageId);
		if (msg?.output) {
			const call = msg.output.find(
				(item: any) => item.type === 'function_call' && item.call_id === callId && item.status === 'pending'
			);
			if (call) {
				call.status = approved ? 'running' : 'rejected';
				allMessages = [...allMessages]; // trigger reactivity
			}
		}

		approveToolCall(chatId, messageId, callId, approved).catch((err) => {
			console.error('[chat] approve error', err);
			// Revert on failure — reload from DB to get true state
			loadChat(chatId!);
		});
	}

	function handleNavigate(messageId: string, direction: -1 | 1) {
		const entry = activePath.find((p) => p.msg.id === messageId);
		if (!entry) return;

		const newIndex = entry.siblingIndex + direction;
		if (newIndex < 0 || newIndex >= entry.siblingIds.length) return;

		const targetId = entry.siblingIds[newIndex];
		const childrenMap = buildChildrenMap(allMessages);
		const leafId = findLeaf(targetId, childrenMap);

		currentMessageId = leafId;
		if (chatId) updateCurrentMessage(chatId, leafId).catch(() => {});
	}

	async function handleRegenerate(messageId: string) {
		const msg = allMessages.find((m) => m.id === messageId);
		if (!msg?.parent_id || !chatId || !selectedModel) return;

		try {
			const result = await apiSendMessage('', selectedModel, workspace, chatId, msg.parent_id, { auto_approve_tools: get(autoApproveTools) });
			await loadChat(result.chat_id);
		} catch (e) {
			console.error('[chat] regenerate error', e);
		}
	}

	async function handleEditMessage(
		messageId: string,
		content: string,
		output: any[] | null,
		submit: boolean
	) {
		const msg = allMessages.find((m) => m.id === messageId);
		if (!msg || !chatId) return;

		if (!submit) {
			// Save in-place
			const updates: { content?: string; output?: any[] } = {};
			if (msg.role === 'user') {
				updates.content = content;
			} else {
				updates.content = content;
				if (output) updates.output = output;
			}
			await updateMessage(chatId, messageId, updates);
			await loadChat(chatId);
			return;
		}

		if (msg.role === 'user') {
			// Send — create new sibling user message + trigger LLM
			try {
				const result = await apiSendMessage(
					content,
					selectedModel,
					workspace,
					chatId,
					msg.parent_id,
					{ auto_approve_tools: get(autoApproveTools) }
				);
				await loadChat(result.chat_id);
			} catch (e) {
				console.error('[chat] edit-send error', e);
			}
		} else {
			// Save As Copy — create new sibling assistant message (no LLM)
			try {
				await createMessage(chatId, msg.parent_id ?? null, 'assistant', content, output ?? undefined);
				await loadChat(chatId);
			} catch (e) {
				console.error('[chat] save-as-copy error', e);
			}
		}
	}

	function updateTab(tid: string, newChatId: string, label: string) {
		currentWorkspace.update((ws) => {
			if (!ws) return ws;
			return {
				...ws,
				groups: ws.groups.map((g) => ({
					...g,
					tabs: g.tabs.map((t) =>
						t.id === tid ? { ...t, path: newChatId, label } : t
					),
				})),
			};
		});
	}
</script>

<div class="flex flex-col h-full bg-white dark:bg-black">
	{#if isLanding}
		<!-- Landing — input + recent chats -->
		<div class="flex-1 overflow-y-auto">
			<div class="max-w-xl mx-auto px-4 flex flex-col" style="padding-top: max(14vh, 48px);">
				<!-- Greeting -->
				<div class="mb-8 text-center">
					<h1 class="text-lg font-normal text-gray-800 dark:text-gray-200 tracking-tight">
						What can I help you with?
					</h1>
				</div>

				<ChatInput
					bind:this={chatInputEl}
					bind:inputText
					bind:selectedModel
					{sending}
					placeholder="Ask anything about {workspaceName}..."
					onsend={send}
				/>
				<ChatHistory chats={previousChats} onopen={openChat} ondelete={deleteChat} />
			</div>
		</div>
	{:else}
		<!-- Conversation view -->
		<div bind:this={messagesEl} class="flex-1 overflow-y-auto" onscroll={handleMessagesScroll}>
			<div class="max-w-2xl mx-auto px-4 pt-4 pb-16 flex flex-col gap-4">
				{#each activePath as { msg, siblingIds, siblingIndex } (msg.id)}
					{#if msg.role === 'user'}
						<UserMessage
							content={msg.content}
							{siblingIndex}
							siblingTotal={siblingIds.length}
							onnavigate={(dir) => handleNavigate(msg.id, dir)}
							onedit={(c, submit) => handleEditMessage(msg.id, c, null, submit)}
						/>
					{:else}
						<AssistantMessage
							content={msg.content}
							done={msg.done}
							output={msg.output}
							{chatId}
							messageId={msg.id}
							{siblingIndex}
							siblingTotal={siblingIds.length}
							onnavigate={(dir) => handleNavigate(msg.id, dir)}
							onregenerate={() => handleRegenerate(msg.id)}
							onedit={(c, o, submit) => handleEditMessage(msg.id, c, o, submit)}
							onapprove={handleApprove}
						/>
					{/if}
				{/each}
			</div>
		</div>

		<!-- Input area -->
		<div class="px-4 py-3">
			<div class="max-w-2xl mx-auto relative">
				{#if !autoScroll && activePath.length > 0}
					<div class="absolute -top-10 left-0 right-0 pr-2 flex justify-end z-30 pointer-events-none">
						<button
							class="bg-white dark:bg-white/20 border border-gray-200 dark:border-gray-700 p-1 rounded-full pointer-events-auto shadow-sm hover:bg-gray-50 dark:hover:bg-white/30 transition-colors"
							onclick={() => { autoScroll = true; scrollToBottom(); }}
							aria-label="Scroll to bottom"
						>
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-gray-500 dark:text-gray-400">
								<path fill-rule="evenodd" d="M10 3a.75.75 0 01.75.75v10.638l3.96-4.158a.75.75 0 111.08 1.04l-5.25 5.5a.75.75 0 01-1.08 0l-5.25-5.5a.75.75 0 111.08-1.04l3.96 4.158V3.75A.75.75 0 0110 3z" clip-rule="evenodd" />
							</svg>
						</button>
					</div>
				{/if}
				<ChatInput
					bind:this={chatInputEl}
					bind:inputText
					bind:selectedModel
					{sending}
					{streaming}
					onsend={send}
					oncancel={handleCancel}
				/>
			</div>
		</div>
	{/if}
</div>
