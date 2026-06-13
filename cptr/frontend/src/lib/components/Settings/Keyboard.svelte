<script lang="ts">
	import {
		keybindings,
		ACTION_IDS,
		ACTION_LABELS,
		DEFAULT_KEYBINDINGS,
		formatChord,
		eventToChord,
		resetKeybindings
	} from '$lib/stores/keybindings';
	import type { ActionId } from '$lib/stores/keybindings';
	import KeyPill from '../KeyPill.svelte';
	import { t } from '$lib/i18n';

	/** Action descriptions for the second line. */
	const ACTION_DESCRIPTIONS: Record<ActionId, string> = $derived({
		newFile: $t('keyboard.newFile'),
		newTerminal: $t('keyboard.newTerminal'),
		newChat: $t('keyboard.newChat'),
		closeTab: $t('keyboard.closeTab'),
		nextTab: $t('keyboard.nextTab'),
		prevTab: $t('keyboard.prevTab'),
		quickOpen: $t('keyboard.quickOpen'),
		openSettings: $t('keyboard.openSettings'),
		toggleSplit: $t('keyboard.toggleSplit'),
		toggleSidebar: $t('keyboard.toggleSidebar')
	});

	let recordingAction = $state<ActionId | null>(null);

	function startRecording(actionId: ActionId) {
		recordingAction = actionId;
	}

	function cancelRecording() {
		recordingAction = null;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (!recordingAction) return;
		e.preventDefault();
		e.stopPropagation();

		const chord = eventToChord(e);
		if (!chord) return; // Pure modifier press, keep waiting

		if (chord === 'ESCAPE') {
			cancelRecording();
			return;
		}

		// Save it
		keybindings.update((current) => ({
			...current,
			[recordingAction!]: chord
		}));
		recordingAction = null;
	}

	function clearBinding(actionId: ActionId) {
		keybindings.update((current) => ({
			...current,
			[actionId]: ''
		}));
	}

	/** Check if a chord is used by another action. */
	function getConflict(actionId: ActionId, chord: string): ActionId | null {
		if (!chord) return null;
		for (const id of ACTION_IDS) {
			if (id !== actionId && $keybindings[id] === chord) return id;
		}
		return null;
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="flex flex-col min-h-full">
	<div class="flex items-center justify-between mb-3">
		<h2 class="text-sm font-medium text-gray-900 dark:text-white">{$t('keyboard.title')}</h2>
		<button
			class="text-[10px] text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors duration-100"
			onclick={resetKeybindings}>{$t('keyboard.resetDefaults')}</button
		>
	</div>

	<!-- Column headers -->
	<div class="flex items-center gap-2 mb-0.5 px-1">
		<span class="flex-1 text-[10px] font-medium text-gray-400 dark:text-gray-600">{$t('keyboard.command')}</span>
		<span class="w-[140px] text-[10px] font-medium text-gray-400 dark:text-gray-600 text-right"
			>{$t('keyboard.keybinding')}</span
		>
	</div>

	<div class="flex flex-col">
		{#each ACTION_IDS as actionId}
			{@const chord = $keybindings[actionId]}
			{@const isRecording = recordingAction === actionId}
			{@const conflict = getConflict(actionId, chord)}

			<div class="shortcut-row">
				<div class="flex-1 min-w-0">
					<div class="text-[11.5px] text-gray-700 dark:text-gray-300">
						{ACTION_LABELS[actionId]}
					</div>
					<div class="text-[10px] text-gray-400 dark:text-gray-600 truncate leading-tight">
						{ACTION_DESCRIPTIONS[actionId]}
					</div>
				</div>

				<div class="w-[140px] flex items-center justify-end shrink-0">
					{#if isRecording}
						<span class="recording-indicator">{$t('keyboard.pressKeys')}</span>
					{:else if chord}
						<button
							class="cursor-pointer"
							onclick={() => startRecording(actionId)}
							title={$t('keyboard.clickToRebind')}
						>
							<KeyPill text={formatChord(chord)} />
						</button>
					{:else}
						<button
							class="text-[10px] text-gray-500 dark:text-gray-600 cursor-pointer hover:text-gray-400 transition-colors duration-75"
							onclick={() => startRecording(actionId)}>{$t('keyboard.unassigned')}</button
						>
					{/if}

					{#if conflict}
						<span
							class="text-[9px] text-amber-500 ml-1"
							title="Also bound to {ACTION_LABELS[conflict]}">!</span
						>
					{/if}
				</div>
			</div>
		{/each}
	</div>

	<p class="text-[10px] text-gray-400 dark:text-gray-600 mt-3">
		{$t('keyboard.rebindHint')}
	</p>
</div>

<style>
	@reference "../../../app.css";

	.shortcut-row {
		@apply flex items-center gap-2 px-1 py-1.5;
		border-bottom: 1px solid rgba(128, 128, 128, 0.04);
	}

	.shortcut-row:last-child {
		border-bottom: none;
	}

	.recording-indicator {
		display: inline-flex;
		align-items: center;
		height: 18px;
		padding: 0 8px;
		border-radius: 4px;
		font-size: 10px;
		font-weight: 500;
		background: rgba(59, 130, 246, 0.1);
		color: rgba(59, 130, 246, 0.7);
		animation: pulse-subtle 1.5s ease-in-out infinite;
	}

	@keyframes pulse-subtle {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.6;
		}
	}

	.kbd-inline {
		@apply inline px-0.5 py-px rounded text-[9px] font-mono bg-gray-100 dark:bg-white/6 text-gray-500;
	}
</style>
