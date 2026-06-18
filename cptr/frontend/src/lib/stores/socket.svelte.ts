/**
 * Shared Socket.IO connection: singleton managed by layout.
 *
 * Any store (chat, future features) registers listeners on this.
 * Layout calls connect() on mount, disconnect() on destroy.
 */

import { io, type Socket } from 'socket.io-client';

let socket: Socket | null = null;
let _connected = $state(false);

function connect() {
	if (socket) return;
	socket = io({
		reconnection: true,
		reconnectionDelay: 1000,
		withCredentials: true
	});

	socket.on('connect', () => {
		_connected = true;
	});

	socket.on('disconnect', () => {
		_connected = false;
	});
}

function disconnect() {
	const currentSocket = socket;
	socket = null;
	currentSocket?.disconnect();
	_connected = false;
}

/** Get the raw socket instance for registering listeners. */
function getSocket(): Socket | null {
	return socket;
}

export const socketStore = {
	connect,
	disconnect,
	getSocket,
	get connected() {
		return _connected;
	}
};
