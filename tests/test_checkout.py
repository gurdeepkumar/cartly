from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest

from src.cartly.models.schemas import (
    CartItem,
    ChatSession,
    CheckoutHandshakeRequest,
    CheckoutStatus,
    SKU,
    ShoppingBasket,
)
from src.cartly.services.checkout import (
    CheckoutConnectionError,
    CheckoutError,
    CheckoutService,
    EmptyBasketError,
)
from src.cartly.services.session import InMemorySessionStore, SessionNotFoundError


@pytest.fixture
def sample_sku():
    return SKU(
        id="sku-oatmilk-01",
        name="Oat Milk 64oz",
        category="dairy",
        price=4.99,
        in_stock=True,
        unit="carton",
        brand="Oatly",
        attributes={"dietary": "vegan"},
    )


@pytest.fixture
def sample_cart_item(sample_sku):
    return CartItem(
        sku=sample_sku,
        quantity=2.0,
        price_per_unit=4.99,
        notes="Keep chilled",
    )


@pytest.fixture
def sample_session(sample_cart_item):
    basket = ShoppingBasket(items=[sample_cart_item], currency="USD")
    return ChatSession(
        session_id="session-test-123",
        user_id="user-test-456",
        basket=basket,
    )


def test_create_checkout_payload_success(sample_session):
    service = CheckoutService()
    payload = service.create_checkout_payload(
        session=sample_session,
        store_id="supermarket-nyc-01",
        metadata={"delivery_slot": "morning"},
    )

    assert payload.session_id == sample_session.session_id
    assert payload.user_id == sample_session.user_id
    assert payload.store_id == "supermarket-nyc-01"
    assert payload.total_items == 1
    assert payload.total_amount == 9.98
    assert payload.currency == "USD"
    assert payload.status == CheckoutStatus.PENDING
    assert len(payload.items) == 1

    line_item = payload.items[0]
    assert line_item.sku_id == "sku-oatmilk-01"
    assert line_item.name == "Oat Milk 64oz"
    assert line_item.quantity == 2.0
    assert line_item.unit_price == 4.99
    assert line_item.subtotal == 9.98
    assert line_item.notes == "Keep chilled"
    assert payload.metadata["delivery_slot"] == "morning"


def test_create_checkout_payload_empty_basket_raises():
    empty_session = ChatSession(
        session_id="session-empty",
        user_id="user-empty",
        basket=ShoppingBasket(items=[]),
    )
    service = CheckoutService()

    with pytest.raises(EmptyBasketError):
        service.create_checkout_payload(session=empty_session)


@pytest.mark.asyncio
async def test_process_handshake_success_mock(sample_session):
    session_store = InMemorySessionStore()
    await session_store.save_session(sample_session)

    service = CheckoutService(session_store=session_store)

    request = CheckoutHandshakeRequest(
        session_id=sample_session.session_id,
        user_id=sample_session.user_id,
        store_id="supermarket-main",
    )

    response = await service.process_handshake(request)

    assert response.success is True
    assert response.checkout_payload.status == CheckoutStatus.COMPLETED
    assert response.confirmation_code is not None
    assert response.confirmation_code.startswith("CONF-")
    assert response.checkout_payload.total_amount == 9.98
    assert "Supermarket checkout handshake completed" in response.message


@pytest.mark.asyncio
async def test_process_handshake_session_not_found():
    session_store = InMemorySessionStore()
    service = CheckoutService(session_store=session_store)

    request = CheckoutHandshakeRequest(
        session_id="nonexistent-session",
        user_id="user-123",
    )

    with pytest.raises(SessionNotFoundError):
        await service.process_handshake(request)


@pytest.mark.asyncio
async def test_process_handshake_external_api_success(sample_session):
    session_store = InMemorySessionStore()
    await session_store.save_session(sample_session)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False

    mock_api_resp = MagicMock()
    mock_api_resp.status_code = 200
    mock_api_resp.json.return_value = {
        "confirmation_code": "EXT-SUPERMARKET-998877",
        "status": "ACCEPTED",
    }
    mock_client.post.return_value = mock_api_resp

    service = CheckoutService(
        session_store=session_store,
        supermarket_api_url="https://api.supermarket.com",
        http_client=mock_client,
    )

    request = CheckoutHandshakeRequest(
        session_id=sample_session.session_id,
        user_id=sample_session.user_id,
    )

    response = await service.process_handshake(request)

    assert response.success is True
    assert response.confirmation_code == "EXT-SUPERMARKET-998877"
    assert response.checkout_payload.status == CheckoutStatus.COMPLETED
    mock_client.post.assert_called_once()
    await service.close()


@pytest.mark.asyncio
async def test_process_handshake_external_api_network_error(sample_session):
    session_store = InMemorySessionStore()
    await session_store.save_session(sample_session)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False
    mock_client.post.side_effect = httpx.RequestError("Gateway unreachable")

    service = CheckoutService(
        session_store=session_store,
        supermarket_api_url="https://api.supermarket.com",
        http_client=mock_client,
    )

    request = CheckoutHandshakeRequest(
        session_id=sample_session.session_id,
        user_id=sample_session.user_id,
    )

    with pytest.raises(CheckoutConnectionError):
        await service.process_handshake(request)

    await service.close()


@pytest.mark.asyncio
async def test_process_handshake_external_api_http_status_error(sample_session):
    session_store = InMemorySessionStore()
    await session_store.save_session(sample_session)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "Internal POS Server Error"

    mock_client.post.return_value = mock_response
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500 Internal Server Error",
        request=MagicMock(),
        response=mock_response,
    )

    service = CheckoutService(
        session_store=session_store,
        supermarket_api_url="https://api.supermarket.com",
        http_client=mock_client,
    )

    request = CheckoutHandshakeRequest(
        session_id=sample_session.session_id,
        user_id=sample_session.user_id,
    )

    with pytest.raises(CheckoutError):
        await service.process_handshake(request)

    await service.close()
