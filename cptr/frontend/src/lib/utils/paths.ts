export function isSupportedWorkspacePath(path: string | null | undefined): path is string {
	if (!path) return false;
	return (
		path.startsWith('/') ||
		path.startsWith('~/') ||
		path.startsWith('~\\') ||
		/^[a-zA-Z]:[\\/]/.test(path) ||
		path.startsWith('\\\\')
	);
}

export function getPathDisplayName(path: string | null | undefined, fallback = ''): string {
	if (!path) return fallback;
	const trimmed = path.replace(/[\\/]+$/, '');
	const parts = trimmed.split(/[\\/]+/).filter(Boolean);
	return parts[parts.length - 1] || trimmed || path || fallback;
}
