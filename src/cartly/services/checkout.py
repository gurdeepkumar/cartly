from typing import Any, Dict, Optional
import logging
from uuid import uuid4

import httpx

from src.cartly.models.schemas import (
    CartItem,
    ChatSession,
    CheckoutHandshakeRequest,
    CheckoutHandshakeResponse,
    CheckoutLineItem,
    CheckoutPayload,
    CheckoutStatus,
    ShoppingBasket,
)
from src.cartly.services.session import BaseSessionStore, SessionNotFoundError

logger = logging.getLogger(__name__)


class CheckoutError(Exception):
    """Base exception for supermarket checkout handshake operations."""

    pass


class EmptyBasketError(CheckoutError):
    """Raised when attempting checkout with an empty shopping basket."""

    pass


class CheckoutConnectionError(CheckoutError):
    """Raised when network communication with external supermarket checkout gateway fails."""

    pass


class CheckoutService:
    """Service handling conversion of active shopping session into supermarket checkout payload

    and executing handshake operations with supermarket systems.
    """

    def __init__(
        self,
        session_store: Optional[BaseSessionStore] = None,
        supermarket_api_url: Optional[str] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        timeout: float = 5.0,
    ):
        self.session_store = session_store
        self.supermarket_api_url = (
            supermarket_api_url.rstrip("/") if supermarket_api_url else None
        )
        self._client = http_client
        self.timeout = timeout

    async def get_client(self) -> httpx.AsyncClient:
        """Get or initialize the httpx AsyncClient."""
        is_closed = getattr(self._client, "is_closed", False)
        closed_flag = isinstance(is_closed, bool) and is_closed

        if self._client is None or closed_flag:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout))
        return self._client

    def create_checkout_payload(
        self,
        session: ChatSession,
        store_id: Optional[str] = "default-supermarket",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CheckoutPayload:
        """Convert a active ChatSession shopping basket into a validated supermarket CheckoutPayload.

        Raises EmptyBasketError if the session basket contains no items.
        """
        if not session.basket or not session.basket.items:
            raise EmptyBasketError(
                f"Cannot process checkout for session '{session.session_id}': Shopping basket is empty."
            )

        checkout_items = []
        for item in session.basket.items:
            line_item = CheckoutLineItem(
                sku_id=item.sku.id,
                name=item.sku.name,
                quantity=item.quantity,
                unit_price=item.price_per_unit,
                subtotal=item.total_price,
                unit=item.sku.unit,
                notes=item.notes,
            )
            checkout_items.append(line_item)

        total_amount = round(sum(item.subtotal for item in checkout_items), 2)
        effective_store_id = store_id or "default-supermarket"

        combined_metadata = dict(session.basket.items[0].sku.attributes or {})
        if metadata:
            combined_metadata.update(metadata)

        payload = CheckoutPayload(
            checkout_id=str(uuid4()),
            session_id=session.session_id,
            user_id=session.user_id,
            store_id=effective_store_id,
            items=checkout_items,
            total_items=len(checkout_items),
            total_amount=total_amount,
            currency=session.basket.currency,
            status=CheckoutStatus.PENDING,
            metadata=combined_metadata,
        )

        return payload

    async def process_handshake(
        self,
        request: CheckoutHandshakeRequest,
        session: Optional[ChatSession] = None,
    ) -> CheckoutHandshakeResponse:
        """Execute supermarket checkout handshake by resolving session, validating basket,

        converting payload, and communicating with external supermarket gateway.
        """
        target_session = session

        if target_session is None:
            if not self.session_store:
                raise CheckoutError(
                    "Session store is not configured for CheckoutService."
                )
            target_session = await self.session_store.get_session(request.session_id)
            if target_session is None:
                raise SessionNotFoundError(
                    f"Session '{request.session_id}' not found for checkout handshake."
                )

        payload = self.create_checkout_payload(
            session=target_session,
            store_id=request.store_id,
            metadata=request.metadata,
        )

        confirmation_code: Optional[str] = None

        if self.supermarket_api_url:
            client = await self.get_client()
            url = f"{self.supermarket_api_url}/checkout"
            try:
                response = await client.post(url, json=payload.model_dump(mode="json"))
                response.raise_for_status()
                data = response.json()
                confirmation_code = data.get("confirmation_code") or data.get("id")
                payload.status = CheckoutStatus.COMPLETED
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                logger.error(
                    f"Supermarket API checkout handshake connection failed for session {request.session_id}: {exc}"
                )
                payload.status = CheckoutStatus.FAILED
                raise CheckoutConnectionError(
                    f"Supermarket checkout gateway error: {exc}"
                ) from exc
            except httpx.HTTPStatusError as exc:
                logger.error(
                    f"Supermarket API returned error HTTP {exc.response.status_code} for session {request.session_id}"
                )
                payload.status = CheckoutStatus.FAILED
                raise CheckoutError(
                    f"Supermarket API failed with status {exc.response.status_code}: {exc.response.text}"
                ) from exc
        else:
            payload.status = CheckoutStatus.COMPLETED
            confirmation_code = f"CONF-{uuid4().hex[:8].upper()}"

        message = (
            f"Supermarket checkout handshake completed successfully. "
            f"{payload.total_items} items total ${payload.total_amount:.2f} {payload.currency}."
        )

        return CheckoutHandshakeResponse(
            success=True,
            checkout_payload=payload,
            message=message,
            confirmation_code=confirmation_code,
        )

    async def close(self) -> None:
        """Release underlying HTTP client resources."""
        if self._client is not None:
            is_closed = getattr(self._client, "is_closed", False)
            if not (isinstance(is_closed, bool) and is_closed):
                if hasattr(self._client, "aclose"):
                    await self._client.aclose()
            self._client = None
