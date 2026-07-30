from unittest.mock import AsyncMock, MagicMock
import pytest
from src.cartly.models.schemas import ChatSession
from src.cartly.services.session import RedisSessionStore


@pytest.mark.asyncio
async def test_redis_session_store_save_and_get():
    mock_redis = AsyncMock()

    session = ChatSession(session_id="sess-1", user_id="user-1")
    serialized = session.model_dump_json()

    mock_redis.get.return_value = serialized

    store = RedisSessionStore(redis_client=mock_redis)

    # Test save
    await store.save_session(session)
    mock_redis.set.assert_called_once()

    # Test get
    retrieved = await store.get_session("sess-1")
    assert retrieved is not None
    assert retrieved.session_id == "sess-1"

    await store.close()
