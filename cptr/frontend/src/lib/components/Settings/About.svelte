<script lang="ts">
	import { t } from '$lib/i18n';
	import { appVersion, showChangelog, updateAvailable, latestVersion } from '$lib/stores';
</script>

<h2 class="text-sm font-medium text-gray-900 dark:text-white mb-4">
	{$t('about.title')}
</h2>

<div>
	<div class="flex items-baseline gap-2">
		<a
			href="https://github.com/open-webui/computer"
			target="_blank"
			rel="noopener noreferrer"
			class="text-xs font-semibold text-gray-900 dark:text-white hover:underline">cptr</a
		>
		{#if $appVersion}
			<button
				onclick={() => showChangelog.set(true)}
				class="text-[11px] text-gray-400 dark:text-gray-600 hover:text-gray-500 dark:hover:text-gray-400 font-mono hover:underline cursor-pointer"
				>v{$appVersion}</button
			>
		{/if}
	</div>

	{#if $updateAvailable}
		<a
			href="https://github.com/open-webui/computer/releases"
			target="_blank"
			rel="noopener noreferrer"
			class="inline-block mt-1 text-[11px] text-blue-500 dark:text-blue-400 hover:text-blue-600 dark:hover:text-blue-300 transition-colors"
		>
			{$t('update.updateAvailable', { version: $latestVersion })}
		</a>
	{/if}

	<p class="text-[13px] text-gray-500 mt-0.5 mb-4">{$t('app.tagline')}</p>

	<h3 class="text-xs text-gray-400 dark:text-gray-600 mb-1">
		{$t('about.license')}
	</h3>
	<p class="text-[11px] text-gray-500 leading-relaxed font-mono whitespace-pre-line">
		<a
			href="https://github.com/open-webui/computer/blob/main/LICENSE"
			target="_blank"
			rel="noopener noreferrer"
			class="underline hover:text-gray-700 dark:hover:text-gray-300">Open Use License</a
		>

		<br />
		Copyright © 2026 Open WebUI Inc. All rights reserved.
	</p>
</div>

<p class="text-[11px] text-gray-300 dark:text-gray-700 pt-8">
	{$t('about.createdBy')}
</p>

