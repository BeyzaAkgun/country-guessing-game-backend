#manager.py
from fastapi import WebSocket
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active: dict[str, list[WebSocket]] = {}
        self.user_map: dict[WebSocket, str] = {}

    async def connect(self, match_id: str, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if match_id not in self.active:
            self.active[match_id] = []
        self.active[match_id].append(websocket)
        self.user_map[websocket] = user_id

    def disconnect(self, match_id: str, websocket: WebSocket):
        if match_id in self.active:
            self.active[match_id] = [ws for ws in self.active[match_id] if ws != websocket]
            if not self.active[match_id]:
                del self.active[match_id]
        self.user_map.pop(websocket, None)

    async def send_to(self, websocket: WebSocket, event: str, data: Any):
        try:
            await websocket.send_text(json.dumps({"event": event, "data": data}))
        except Exception as e:
            logger.warning(f"send_to failed: {e}")

    async def broadcast(self, match_id: str, event: str, data: Any):
        if match_id not in self.active:
            return
        message = json.dumps({"event": event, "data": data})
        dead = []
        for ws in list(self.active.get(match_id, [])):
            try:
                await ws.send_text(message)
            except Exception as e:
                logger.warning(f"broadcast failed in {match_id}: {e}")
                dead.append(ws)
        for ws in dead:
            self.disconnect(match_id, ws)

    async def broadcast_except(self, match_id: str, exclude: WebSocket, event: str, data: Any):
        if match_id not in self.active:
            return
        message = json.dumps({"event": event, "data": data})
        for ws in list(self.active.get(match_id, [])):
            if ws != exclude:
                try:
                    await ws.send_text(message)
                except Exception as e:
                    logger.warning(f"broadcast_except failed: {e}")

    def get_user_id(self, websocket: WebSocket) -> str | None:
        return self.user_map.get(websocket)

    def get_connection_count(self, match_id: str) -> int:
        return len(self.active.get(match_id, []))


manager = ConnectionManager()