import asyncio
import pytest
from app.services.conversations import ConversationStore, ConversationNotFound


def test_waiting_turn_cannot_be_evicted_or_deleted():
    async def scenario():
        store = ConversationStore(limit=1)
        entered = asyncio.Event()
        release = asyncio.Event()
        async with store.turn("alice") as first:
            identifier = first.id

            async def second_turn():
                async with store.turn("alice", identifier):
                    entered.set()
                    await release.wait()

            waiting = asyncio.create_task(second_turn())
            await asyncio.sleep(0)
            assert first.active_turns == 2
            with pytest.raises(RuntimeError):
                store.delete("alice", identifier)
        await entered.wait()
        with pytest.raises(RuntimeError):
            async with store.turn("bob"):
                pass
        release.set()
        await waiting
        assert first.active_turns == 0
        async with store.turn("bob") as replacement:
            assert replacement.id != identifier
        with pytest.raises(ConversationNotFound):
            store.get("alice", identifier)

    asyncio.run(scenario())
