<script lang="ts">
	import { tooltip } from '$lib/tooltip';
	import Icon from '../Icon.svelte';
	import { t } from '$lib/i18n';

	interface Props {
		content: string;
		filePath: string;
	}

	let { content, filePath }: Props = $props();

	let iframeKey = $state(0);

	// Use /api/workspace/files/serve/ for path-based serving (resolves relative refs)
	let serveUrl = $derived(() => {
		const stripped = filePath.startsWith('/') ? filePath.slice(1) : filePath;
		return `/api/workspace/files/serve/${stripped}`;
	});
</script>

<div class="html-preview">
	{#key iframeKey}
		<iframe
			src={serveUrl()}
			title={$t('preview.htmlTitle')}
			sandbox="allow-scripts allow-same-origin"
			class="preview-iframe"
		></iframe>
	{/key}
</div>

<style>
	@reference "../../../app.css";

	.html-preview {
		display: flex;
		flex-direction: column;
		height: 100%;
		overflow: hidden;
	}

	.preview-iframe {
		width: 100%;
		height: 100%;
		border: none;
		background: white;
	}
</style>
