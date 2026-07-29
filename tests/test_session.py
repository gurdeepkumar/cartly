from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.cartly.models.schemas import (
    CartItem,
    ChatMessage,
    ChatSession,
    PendingClarification,
    SKU,
    ShoppingBasket,
)
from src.cartly.services.session import (
    InMemorySessionStore,
    RedisSessionStore,
    SessionNotFoundError,
    SessionStoreError,
)


@pytest.mark.asyncio
async def test_in_memory_session_store_crud():
    store = InMemorySessionStore(default_window_size=5)

    session_id = "sess-001"
    session = ChatSession(session_id=session_id, user_id="user-1")

    assert await store.exists(session_id) is False
    assert await store.get_session(session_id) is None

    # Save session
    await store.save_session(session)
    assert await store.exists(session_id) is True

    retrieved = await store.get_session(session_id)
    assert retrieved is not None
    assert retrieved.session_id == session_id
    assert retrieved.user_id == "user-1"

    # Delete session
    deleted = await store.delete_session(session_id)
    assert deleted is True
    assert await store.exists(session_id) is False
    assert await store.delete_session("non-existent") is False

    await store.close()


@pytest.mark.asyncio
async def test_in_memory_session_store_sliding_window():
    store = InMemorySessionStore(default_window_size=3)
    session_id = "sess-window"
    session = ChatSession(session_id=session_id, user_id="user-1")
    await store.save_session(session)

    # Add 5 messages into window size 3
    for i in range(1, 6):
        msg = ChatMessage(
            role="user" if i % 2 != 0 else "assistant", content=f"Message {i}"
        )
        updated = await store.add_message(session_id, msg)

    history = await store.get_windowed_history(session_id)
    assert len(history) == 3
    assert history[0].content == "Message 3"
    assert history[1].content == "Message 4"
    assert history[2].content == "Message 5"

    await store.close()


@pytest.mark.asyncio
async def test_in_memory_session_store_basket_and_clarification():
    store = InMemorySessionStore()
    session_id = "sess-basket"
    session = ChatSession(session_id=session_id, user_id="user-1")
    await store.save_session(session)

    # Update basket
    sku = SKU(id="sku-1", name="Apple", price=1.20)
    basket = ShoppingBasket(items=[CartItem(sku=sku, quantity=2.0)])

    updated_session = await store.update_basket(session_id, basket)
    assert updated_session.basket.total_amount == 2.40
    assert updated_session.basket.item_count == 1

    # Set pending clarification
    clarification = PendingClarification(
        question="Which brand of apples?",
        options=["Fuji", "Gala"],
        target_item="apple",
    )
    session_with_clar = await store.set_pending_clarification(session_id, clarification)
    assert session_with_clar.pending_clarification is not None
    assert session_with_clar.pending_clarification.question == "Which brand of apples?"

    # Clear clarification
    session_cleared = await store.set_pending_clarification(session_id, None)
    assert session_cleared.pending_clarification is None

    # Error handling for non-existent session
    with pytest.raises(SessionNotFoundError):
        await store.update_basket("missing-session", basket)

    with pytest.raises(SessionNotFoundError):
        await store.add_message(
            "missing-session", ChatMessage(role="user", content="hi")
        )

    await store.close()


@pytest.mark.asyncio
async def test_redis_session_store_mocked_operations():
    mock_redis = AsyncMock()

    store = RedisSessionStore(
        redis_client=mock_redis,
        default_window_size=3,
        default_ttl=3600,
        retry_attempts=2,
    )

    session_id = "redis-sess-1"
    session = ChatSession(session_id=session_id, user_id="user-redis")
    serialized_session = session.model_dump_json()

    # Get non-existent session
    mock_redis.get.return_value = None
    res = await store.get_session(session_id)
    assert res is None
    mock_redis.get.assert_called_with(f"cartly:session:{session_id}")

    # Save session
    await store.save_session(session)
    mock_redis.set.assert_called_once()
    call_args = mock_redis.set.call_args
    assert call_args[0][0] == f"cartly:session:{session_id}"
    assert call_args[1]["ex"] == 3600

    # Get existing session
    mock_redis.get.return_value = serialized_session
    retrieved = await store.get_session(session_id)
    assert retrieved is not None
    assert retrieved.session_id == session_id
    assert retrieved.user_id == "user-redis"

    # Exists check
    mock_redis.exists.return_value = 1
    assert await store.exists(session_id) is True

    # Delete session
    mock_redis.delete.return_value = 1
    assert await store.delete_session(session_id) is True

    await store.close()


@pytest.mark.asyncio
async def test_redis_session_store_retry_and_resilience():
    from redis.exceptions import ConnectionError as RedisConnectionError

    mock_redis = AsyncMock()
    # First call raises ConnectionError, second call succeeds
    mock_redis.get.side_effect = [RedisConnectionError("Connection lost"), None]

    store = RedisSessionStore(
        redis_client=mock_redis,
        retry_attempts=2,
    )

    # Re-initialization mock
    with patch("src.cartly.services.session.aioredis.from_url") as mock_from_url:
        mock_from_url.return_value = mock_redis
        result = await store.get_session("retry-session")
        assert result is None
        assert mock_redis.get.call_count == 2

    await store.close()


@pytest.mark.asyncio
async def test_redis_session_store_corrupted_data_error():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "invalid-json-content"

    store = RedisSessionStore(redis_client=mock_redis)

    with pytest.raises(SessionStoreError):
        await store.get_session("corrupt-session")

    await store.close()
