<script lang="ts">
	import { tick } from 'svelte';
	import { chatModels } from '$lib/stores/chat';
	import DropdownMenu from '../DropdownMenu.svelte';

	interface Props {
		selectedModel: string;
	}
	let { selectedModel = $bindable() }: Props = $props();

	let btnEl: HTMLButtonElement | undefined = $state();
	let searchInputEl: HTMLInputElement | undefined = $state();
	let open = $state(false);
	let search = $state('');

	const filtered = $derived(
		search.trim()
			? $chatModels.filter((m) => m.name.toLowerCase().includes(search.toLowerCase()))
			: $chatModels
	);

	const menuItems = $derived(
		filtered.map((m) => ({
			label: m.name,
			active: m.id === selectedModel,
			check: true,
			onclick: () => {
				selectedModel = m.id;
			}
		}))
	);

	async function toggle() {
		if ($chatModels.length === 0) return;
		if (open) {
			open = false;
			return;
		}
		open = true;
		search = '';
		await tick();
		// Focus search after DropdownMenu renders
		await tick();
		searchInputEl?.focus();
	}
</script>

<button
	bind:this={btnEl}
	class="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-400 hover:bg-gray-50 dark:hover:bg-white/5 transition-colors duration-100"
	onclick={toggle}
>
	<span class="truncate max-w-[160px]"
		>{$chatModels.length === 0
			? 'No models available'
			: $chatModels.find((m) => m.id === selectedModel)?.name || 'Select model'}</span
	>
	{#if $chatModels.length > 0}
		<svg
			class="w-3 h-3 opacity-50"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2.5"
			stroke-linecap="round"
			stroke-linejoin="round"
		>
			<polyline points="6 9 12 15 18 9" />
		</svg>
	{/if}
</button>

{#if open && btnEl && $chatModels.length > 0}
	<DropdownMenu
		items={menuItems}
		anchor={btnEl}
		onclose={() => (open = false)}
		preferAbove={true}
		maxHeight="15rem"
		className="w-48"
		align="end"
	>
		{#snippet header()}
			<div class="flex items-center gap-1.5 h-6 px-2 mt-0.5">
				<svg
					class="w-3 h-3 shrink-0 text-gray-300 dark:text-gray-600"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
				>
					<circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
				</svg>
				<input
					bind:this={searchInputEl}
					bind:value={search}
					placeholder="Search..."
					class="w-full bg-transparent text-[11px] text-gray-500 dark:text-gray-400 placeholder:text-gray-300 dark:placeholder:text-gray-600 outline-none"
					onkeydown={(e) => {
						if (e.key === 'Escape') open = false;
					}}
				/>
			</div>
		{/snippet}
		{#snippet empty()}
			<div class="px-3 py-1.5 text-[11px] text-gray-400 dark:text-gray-500 text-center">No matches</div>
		{/snippet}
	</DropdownMenu>
{/if}
