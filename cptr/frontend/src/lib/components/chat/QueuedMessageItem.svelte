<script lang="ts">
	interface Props {
		id: string;
		content: string;
		onsendnow: (id: string) => void;
		onedit: (id: string) => void;
		ondelete: (id: string) => void;
	}
	let { id, content, onsendnow, onedit, ondelete }: Props = $props();

	import { t } from '$lib/i18n';
</script>

<div class="flex items-center gap-2 px-2 py-1">
	<!-- Queue indicator: reply/forward arrow -->
	<div class="shrink-0 text-gray-400 dark:text-gray-600">
		<svg
			class="w-3 h-3"
			fill="none"
			stroke="currentColor"
			viewBox="0 0 24 24"
			stroke-width="1.5"
			stroke-linecap="round"
			stroke-linejoin="round"
		>
			<path d="M13.25 19.25L16.75 15.75L13.25 12.25" />
			<path d="M16.75 15.75H10.75C8.54086 15.75 6.75 13.9591 6.75 11.75V7.5" />
		</svg>
	</div>

	<!-- Content -->
	<p class="flex-1 min-w-0 text-xs text-gray-600 dark:text-gray-400 truncate">{content || ''}</p>

	<!-- Actions -->
	<div class="flex items-center shrink-0">
		<!-- Send now -->
		<button
			type="button"
			class="p-1 rounded-md text-gray-400 dark:text-gray-600 hover:text-gray-600 dark:hover:text-gray-300 transition-colors duration-100"
			title={$t('chat.sendNow')}
			onclick={() => onsendnow(id)}
		>
			<svg
				class="w-3 h-3"
				fill="none"
				stroke="currentColor"
				viewBox="0 0 24 24"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
			>
				<path d="M4.5 10.5 12 3m0 0 7.5 7.5M12 3v18" />
			</svg>
		</button>
		<!-- Edit -->
		<button
			type="button"
			class="p-1 rounded-md text-gray-400 dark:text-gray-600 hover:text-gray-600 dark:hover:text-gray-300 transition-colors duration-100"
			title={$t('common.edit')}
			onclick={() => onedit(id)}
		>
			<svg
				class="w-3 h-3"
				fill="none"
				stroke="currentColor"
				viewBox="0 0 24 24"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
			>
				<path
					d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487zm0 0L19.5 7.125"
				/>
			</svg>
		</button>
		<!-- Remove -->
		<button
			type="button"
			class="p-1 rounded-md text-gray-400 dark:text-gray-600 hover:text-gray-600 dark:hover:text-gray-300 transition-colors duration-100"
			title={$t('common.remove')}
			onclick={() => ondelete(id)}
		>
			<svg
				class="w-3 h-3"
				fill="none"
				stroke="currentColor"
				viewBox="0 0 24 24"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
			>
				<path d="M6 18L18 6M6 6l12 12" />
			</svg>
		</button>
	</div>
</div>
