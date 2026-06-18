<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { t } from '$lib/i18n';
	import { socketStore } from '$lib/stores/socket.svelte';

	let isOnline = $state(true);
	let toastId: string | number | undefined;
	let hasSeenSocketConnection = $state(false);

	function showOffline() {
		if (!isOnline) return;
		isOnline = false;
		toastId = toast.error($t('pwa.reconnecting'), { duration: Infinity });
	}

	function showOnline() {
		if (isOnline) return;
		isOnline = true;
		if (toastId) toast.dismiss(toastId);
		toastId = undefined;
	}

	function handleOnline() {
		if (socketStore.connected) {
			showOnline();
		}
	}

	$effect(() => {
		const socket = socketStore.getSocket();
		const connected = socketStore.connected;

		if (!socket) {
			hasSeenSocketConnection = false;
			showOnline();
			return;
		}

		if (connected) {
			hasSeenSocketConnection = true;
			showOnline();
		} else if (hasSeenSocketConnection) {
			showOffline();
		}
	});

	onMount(() => {
		window.addEventListener('offline', showOffline);
		window.addEventListener('online', handleOnline);

		return () => {
			window.removeEventListener('offline', showOffline);
			window.removeEventListener('online', handleOnline);
			if (toastId) toast.dismiss(toastId);
		};
	});
</script>
