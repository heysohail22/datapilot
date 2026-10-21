"""Bounded, single-process history with owner isolation and per-thread serialization."""

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


class ConversationNotFound(Exception):
    pass


@dataclass
class Conversation:
    id: str
    owner: str
    title: str = "New Conversation"
    messages: list[dict] = field(default_factory=list)
    context: dict | None = None
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active_turns: int = 0


class ConversationStore:
    def __init__(self, limit=200):
        self.limit = limit
        self._items: OrderedDict[str, Conversation] = OrderedDict()

    @asynccontextmanager
    async def turn(self, owner, conversation_id=None):
        conv = self._items.get(conversation_id) if conversation_id else None
        if conv and conv.owner != owner:
            raise ConversationNotFound()
        if conv is None:
            if conversation_id:
                # Unknown IDs can be frontend-local UUIDs. Never accept them as canonical IDs.
                # Return not found; API adapter may explicitly start a fresh conversation.
                raise ConversationNotFound()
            while len(self._items) >= self.limit:
                candidate = next(
                    (key for key, item in self._items.items() if not item.active_turns),
                    None,
                )
                if candidate is None:
                    raise RuntimeError("Conversation capacity reached")
                del self._items[candidate]
            conv = Conversation(id=str(uuid4()), owner=owner)
            self._items[conv.id] = conv
        conv.active_turns += 1
        try:
            async with conv.lock:
                self._items.move_to_end(conv.id)
                yield conv
        finally:
            conv.active_turns -= 1

    def append(self, conv, question, response, context):
        now = datetime.now(timezone.utc).isoformat()
        if not conv.messages:
            conv.title = question[:100]
        conv.messages.extend(
            [
                {
                    "id": str(uuid4()),
                    "role": "user",
                    "content": question,
                    "timestamp": now,
                },
                {
                    "id": str(uuid4()),
                    "role": "assistant",
                    "content": response.message,
                    "timestamp": now,
                    "sql": response.sql,
                    "data": response.data,
                    "chart_config": response.chart.model_dump()
                    if response.chart
                    else None,
                    "thought_trace": response.thought_trace,
                },
            ]
        )
        conv.messages = conv.messages[-40:]
        conv.context, conv.updated_at = context, now

    def list(self, owner):
        return [
            {
                "id": c.id,
                "title": c.title,
                "message_count": len(c.messages),
                "updated_at": c.updated_at,
            }
            for c in reversed(self._items.values())
            if c.owner == owner
        ]

    def get(self, owner, conversation_id):
        conv = self._items.get(conversation_id)
        if not conv or conv.owner != owner:
            raise ConversationNotFound()
        return {
            "id": conv.id,
            "title": conv.title,
            "summary": None,
            "messages": conv.messages,
        }

    def delete(self, owner, conversation_id):
        self.get(owner, conversation_id)
        if self._items[conversation_id].active_turns:
            raise RuntimeError("Conversation has an active request")
        del self._items[conversation_id]
