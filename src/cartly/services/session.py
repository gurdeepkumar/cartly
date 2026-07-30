from abc import ABC, abstractmethod
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
import redis.asyncio as aioredis
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
    RedisError,
    TimeoutError as RedisTimeoutError,
)

from src.cartly.config import settings
from src.cartly.models.schemas import (
    ChatMessage,
    ChatSession,
    PendingClarification,
    ShoppingBasket,
)

logger = logging.getLogger(__name__)


class SessionStoreError(Exception):
    """Base exception for session store operations."""

    pass


class SessionNotFoundError(SessionStoreError):
    """Raised when a requested session is not found."""

    pass


class BaseSessionStore(ABC):
    """Abstract interface for multi-turn session memory stores."""

    def __init__(
        self,
        default_window_size: int = settings.SLIDING_WINDOW_SIZE,
        default_ttl: int = settings.SESSION_TTL_SECONDS,
    ):
        self.default_window_size = default_window_size
        self.default_ttl = default_ttl

    @abstractmethod
    async def get_session(self, session_id: str) -> Optional[ChatSession]:
        """Retrieve a ChatSession by its session ID."""
        pass

    @abstractmethod
    async def save_session(
        self, session: ChatSession, ttl: Optional[int] = None
    ) -> None:
        """Save or update a ChatSession with optional TTL in seconds."""
        pass

    @abstractmethod
    async def delete_session(self, session_id: str) -> bool:
        """Delete a ChatSession by session ID. Returns True if deleted."""
        pass

    @abstractmethod
    async def exists(self, session_id: str) -> bool:
        """Check if a session ID exists."""
        pass

    @abstractmethod
    async def add_message(
        self, session_id: str, message: ChatMessage, window_size: Optional[int] = None
    ) -> ChatSession:
        """Add a ChatMessage to session history, enforcing sliding window limit."""
        pass

    @abstractmethod
    async def get_windowed_history(
        self, session_id: str, window_size: Optional[int] = None
    ) -> List[ChatMessage]:
        """Get the sliding window history for a session."""
        pass

    @abstractmethod
    async def update_basket(
        self, session_id: str, basket: ShoppingBasket
    ) -> ChatSession:
        """Update the shopping basket for a session."""
        pass

    @abstractmethod
    async def set_pending_clarification(
        self, session_id: str, pending: Optional[PendingClarification]
    ) -> ChatSession:
        """Set or clear pending clarification for a session."""
        pass

    @abstractmethod
    async def clear_session(self, session_id: str) -> bool:
        """Clear all state for a session."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close any open connections or release resources."""
        pass


class RedisSessionStore(BaseSessionStore):
    """Production-grade Redis adapter for session memory store with resilience and connection pooling."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        redis_client: Optional[aioredis.Redis] = None,
        default_window_size: int = settings.SLIDING_WINDOW_SIZE,
        default_ttl: int = settings.SESSION_TTL_SECONDS,
        key_prefix: str = "cartly:session:",
        retry_attempts: int = 3,
    ):
        super().__init__(
            default_window_size=default_window_size, default_ttl=default_ttl
        )
        self.redis_url = redis_url or settings.REDIS_URL
        self.key_prefix = key_prefix
        self.retry_attempts = retry_attempts
        self._client: Optional[aioredis.Redis] = redis_client

    async def get_client(self) -> aioredis.Redis:
        """Get or initialize Redis client with connection pooling and resilience."""
        if self._client is None:
            try:
                self._client = aioredis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=5.0,
                    socket_timeout=5.0,
                    health_check_interval=30,
                )
            except Exception as e:
                logger.error(f"Failed to create Redis client for {self.redis_url}: {e}")
                raise SessionStoreError(f"Redis initialization failed: {e}") from e
        return self._client

    def _get_key(self, session_id: str) -> str:
        return f"{self.key_prefix}{session_id}"

    async def _execute_with_retry(self, func, *args, **kwargs):
        """Helper to execute Redis commands with automatic reconnection and retry logic."""
        last_exception = None
        for attempt in range(1, self.retry_attempts + 1):
            try:
                client = await self.get_client()
                return await func(client, *args, **kwargs)
            except (RedisConnectionError, RedisTimeoutError) as e:
                last_exception = e
                logger.warning(
                    f"Redis connection attempt {attempt}/{self.retry_attempts} failed: {e}"
                )
                # Re-initialize client on connection loss
                if self._client is not None:
                    try:
                        await self._client.aclose()
                    except Exception:
                        pass
                    self._client = None
            except RedisError as e:
                logger.error(f"Redis operation error: {e}")
                raise SessionStoreError(f"Redis error: {e}") from e

        raise SessionStoreError(
            f"Redis operation failed after {self.retry_attempts} attempts: {last_exception}"
        ) from last_exception

    async def get_session(self, session_id: str) -> Optional[ChatSession]:
        key = self._get_key(session_id)

        async def _get(client):
            return await client.get(key)

        data = await self._execute_with_retry(_get)
        if not data:
            return None

        try:
            return ChatSession.model_validate_json(data)
        except Exception as e:
            logger.error(
                f"Failed to deserialize ChatSession JSON for {session_id}: {e}"
            )
            raise SessionStoreError(
                f"Corrupted session data for {session_id}: {e}"
            ) from e

    async def save_session(
        self, session: ChatSession, ttl: Optional[int] = None
    ) -> None:
        key = self._get_key(session.session_id)
        session.updated_at = datetime.now(timezone.utc)
        effective_ttl = ttl if ttl is not None else self.default_ttl
        serialized = session.model_dump_json()

        async def _save(client):
            await client.set(key, serialized, ex=effective_ttl)

        await self._execute_with_retry(_save)

    async def delete_session(self, session_id: str) -> bool:
        key = self._get_key(session_id)

        async def _del(client):
            result = await client.delete(key)
            return result > 0

        return await self._execute_with_retry(_del)

    async def exists(self, session_id: str) -> bool:
        key = self._get_key(session_id)

        async def _exists(client):
            return await client.exists(key) > 0

        return await self._execute_with_retry(_exists)

    async def add_message(
        self, session_id: str, message: ChatMessage, window_size: Optional[int] = None
    ) -> ChatSession:
        session = await self.get_session(session_id)
        if not session:
            raise SessionNotFoundError(f"Session {session_id} not found")

        session.history.append(message)
        max_size = window_size or self.default_window_size
        if len(session.history) > max_size:
            session.history = session.history[-max_size:]

        await self.save_session(session)
        return session

    async def get_windowed_history(
        self, session_id: str, window_size: Optional[int] = None
    ) -> List[ChatMessage]:
        session = await self.get_session(session_id)
        if not session:
            return []
        max_size = window_size or self.default_window_size
        return session.history[-max_size:]

    async def update_basket(
        self, session_id: str, basket: ShoppingBasket
    ) -> ChatSession:
        session = await self.get_session(session_id)
        if not session:
            raise SessionNotFoundError(f"Session {session_id} not found")
        session.basket = basket
        await self.save_session(session)
        return session

    async def set_pending_clarification(
        self, session_id: str, pending: Optional[PendingClarification]
    ) -> ChatSession:
        session = await self.get_session(session_id)
        if not session:
            raise SessionNotFoundError(f"Session {session_id} not found")
        session.pending_clarification = pending
        await self.save_session(session)
        return session

    async def clear_session(self, session_id: str) -> bool:
        return await self.delete_session(session_id)

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as e:
                logger.warning(f"Error while closing Redis client: {e}")
            finally:
                self._client = None
