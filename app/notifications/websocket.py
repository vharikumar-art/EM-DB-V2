import asyncio
from collections import defaultdict
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        # channel_id -> list of active websocket connections
        # For employees: channel_id = employee record id
        # For admins:    channel_id = user_id
        self.active_connections: dict[str, list[WebSocket]] = defaultdict(list)

        # Track which channel_ids belong to admins so we can broadcast to them
        self.admin_channel_ids: set[str] = set()

    async def connect(self, websocket: WebSocket, channel_id: str, is_admin: bool = False):
        await websocket.accept()
        self.active_connections[channel_id].append(websocket)
        if is_admin:
            self.admin_channel_ids.add(channel_id)

    def disconnect(self, websocket: WebSocket, channel_id: str):
        if websocket in self.active_connections[channel_id]:
            self.active_connections[channel_id].remove(websocket)
        # Clean up admin set if no more connections on that channel
        if not self.active_connections[channel_id] and channel_id in self.admin_channel_ids:
            self.admin_channel_ids.discard(channel_id)

    async def send_personal_message(self, message: dict, channel_id: str):
        """Push a message to all connections on a specific channel."""
        if channel_id in self.active_connections:
            for connection in self.active_connections[channel_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass

    async def broadcast_to_admins(self, message: dict, exclude_channel: str | None = None):
        """Push a message to every connected admin channel (optionally skip one)."""
        for admin_id in list(self.admin_channel_ids):
            if admin_id == exclude_channel:
                continue
            await self.send_personal_message(message, admin_id)


manager = ConnectionManager()

