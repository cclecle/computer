/**
 * Chat state: tracks whether chat is available (at least one connection configured).
 */
import { writable, get } from 'svelte/store';
import { toast } from 'svelte-sonner';
import { fetchJSON } from '$lib/apis';
import { socketStore } from '$lib/stores/socket.svelte';
import { activeTab } from '$lib/stores';

export const chatEnabled = writable<boolean>(false);

/** Set of tab IDs whose chat is currently streaming (assistant message not done). */
export const streamingChatTabs = writable<Set<string>>(new Set());

/**
 * Maps chatId -> tabId so we can clear streamingChatTabs from a global
 * socket listener even when the ChatPanel component is unmounted.
 */
const chatToTab = new Map<string, string>();

export function registerStreamingChat(chatId: string, tabId: string) {
	chatToTab.set(chatId, tabId);
}

export function unregisterStreamingChat(chatId: string) {
	chatToTab.delete(chatId);
}

/**
 * Bind a global socket listener that clears streamingChatTabs when a
 * chat's "done" event arrives -- even if the ChatPanel is not mounted.
 * Also fires browser notifications and in-app toasts.
 * Called once from the app layout.
 */
let globalListenerBound = false;

/** Whether browser notifications are enabled (persisted to localStorage). */
export const notificationsEnabled = writable<boolean>(
	typeof localStorage !== 'undefined'
		? localStorage.getItem('notificationsEnabled') === 'true'
		: false
);
notificationsEnabled.subscribe((v) => {
	if (typeof localStorage !== 'undefined') localStorage.setItem('notificationsEnabled', String(v));
});

/** Whether notification sound is enabled (persisted to localStorage). */
export const notificationSound = writable<boolean>(
	typeof localStorage !== 'undefined' ? localStorage.getItem('notificationSound') !== 'false' : true
);
notificationSound.subscribe((v) => {
	if (typeof localStorage !== 'undefined') localStorage.setItem('notificationSound', String(v));
});

export function bindGlobalChatListener() {
	if (globalListenerBound) return;

	socketStore.on(
		'events:chat',
		(data: {
			chat_id: string;
			done?: boolean;
			title?: string;
			content?: string;
			workspace?: string;
		}) => {
			if (!data.done) return;

			// Clear streaming indicator for the tab
			const tabId = chatToTab.get(data.chat_id);
			if (tabId) {
				streamingChatTabs.update((s) => {
					const next = new Set(s);
					next.delete(tabId);
					return next;
				});
			}

			// ── Notifications ──────────────────────────────────
			// Skip if user is actively viewing this chat
			const currentTab = get(activeTab);
			const isViewingThisChat =
				!document.hidden && currentTab?.type === 'chat' && currentTab?.path === data.chat_id;

			if (isViewingThisChat) return;

			const wsLabel = data.workspace ? `[${data.workspace}] ` : '';
			const title = `${wsLabel}${data.title || 'Chat'}`;
			const body = data.content || '';

			// In-app toast
			import('$lib/components/NotificationToast.svelte').then((mod) => {
				const chatId = data.chat_id;
				const toastId = toast.custom(mod.default, {
					componentProps: {
						title,
						content: body,
						onClick: async () => {
							const { goto } = await import('$app/navigation');
							const wsParam = data.workspace
								? `workspace=${encodeURIComponent(data.workspace)}&`
								: '';
							await goto(`/?${wsParam}chatId=${encodeURIComponent(chatId)}`);
							toast.dismiss(toastId);
						},
						onclose: () => {
							toast.dismiss(toastId);
						}
					},
					duration: 10000,
					unstyled: true
				});
			});

			// Browser notification (only when tab is hidden)
			if (document.hidden && get(notificationsEnabled)) {
				try {
					new Notification(`${title} • cptr`, {
						body: body.slice(0, 200),
						icon: '/favicon.png'
					});
				} catch {}
			}
		}
	);

	globalListenerBound = true;
}

export interface ChatModel {
	id: string;
	name: string;
	provider: string;
	connection_id: string;
}

export const chatModels = writable<ChatModel[]>([]);
export const defaultModel = writable<string | null>(null);

export async function refreshChatState() {
	try {
		const data = await fetchJSON<{ models: ChatModel[]; default: string | null }>(
			'/api/chats/models'
		);
		chatModels.set(data.models);
		defaultModel.set(data.default);
		chatEnabled.set(data.models.length > 0);
	} catch {
		chatEnabled.set(false);
		chatModels.set([]);
	}
}
