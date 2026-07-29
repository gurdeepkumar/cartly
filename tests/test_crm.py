from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from src.cartly.services.crm import (
    CRMConnectionError,
    CRMError,
    MockCRMAdapter,
    PastOrder,
    PastOrderItem,
    RestCRMAdapter,
    UserContext,
    UserNotFoundError,
    UserProfile,
)


@pytest.mark.asyncio
async def test_mock_crm_adapter_seeded_data():
    adapter = MockCRMAdapter()

    # Get user profile for seeded user
    profile = await adapter.get_user_profile("user-123")
    assert profile is not None
    assert profile.user_id == "user-123"
    assert profile.name == "Jane Doe"
    assert profile.preferred_brands.get("milk") == "Oatly"

    # Preferred brand check
    brand = await adapter.get_preferred_brand("user-123", "milk")
    assert brand == "Oatly"
    assert await adapter.get_preferred_brand("user-123", "nonexistent_cat") is None

    # Past orders check
    orders = await adapter.get_past_orders("user-123")
    assert len(orders) == 1
    assert orders[0].order_id == "ord-9901"
    assert len(orders[0].items) == 2

    # User context check
    context = await adapter.get_user_context("user-123")
    assert context.user_profile.user_id == "user-123"
    assert len(context.past_orders) == 1

    await adapter.close()


@pytest.mark.asyncio
async def test_mock_crm_adapter_custom_registration_and_fallback():
    adapter = MockCRMAdapter(fallback_to_default=True)

    # Register custom profile
    custom_profile = UserProfile(
        user_id="user-custom",
        name="Alice Smith",
        preferred_brands={"yogurt": "Chobani"},
    )
    adapter.register_user_profile(custom_profile)

    retrieved = await adapter.get_user_profile("user-custom")
    assert retrieved is not None
    assert retrieved.name == "Alice Smith"

    # Test unknown user with fallback=True
    guest_profile = await adapter.get_user_profile("unknown-user")
    assert guest_profile is not None
    assert guest_profile.name == "Guest User"
    assert guest_profile.user_id == "unknown-user"

    # Test with fallback=False
    strict_adapter = MockCRMAdapter(fallback_to_default=False)
    assert await strict_adapter.get_user_profile("unknown-user") is None

    with pytest.raises(UserNotFoundError):
        await strict_adapter.get_user_context("unknown-user")

    await adapter.close()
    await strict_adapter.close()


@pytest.mark.asyncio
async def test_rest_crm_adapter_success():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False

    # Mock user profile response
    profile_data = {
        "user_id": "user-rest-1",
        "name": "Bob Martin",
        "email": "bob@example.com",
        "preferred_brands": {"cheese": "Tillamook"},
        "dietary_preferences": ["gluten-free"],
        "favorite_skus": ["sku-cheese-101"],
    }
    mock_profile_resp = MagicMock()
    mock_profile_resp.status_code = 200
    mock_profile_resp.json.return_value = profile_data

    # Mock past orders response
    orders_data = [
        {
            "order_id": "ord-rest-101",
            "items": [
                {
                    "sku_id": "sku-cheese-101",
                    "name": "Tillamook Cheddar",
                    "quantity": 1.0,
                    "unit_price": 4.50,
                }
            ],
            "total_amount": 4.50,
        }
    ]
    mock_orders_resp = MagicMock()
    mock_orders_resp.status_code = 200
    mock_orders_resp.json.return_value = orders_data

    def client_get_side_effect(url, **kwargs):
        if url == "/users/user-rest-1":
            return mock_profile_resp
        elif url == "/users/user-rest-1/orders":
            return mock_orders_resp
        elif url == "/users/user-rest-1/context":
            mock_404 = MagicMock()
            mock_404.status_code = 404
            return mock_404
        raise ValueError(f"Unexpected url: {url}")

    mock_client.get.side_effect = client_get_side_effect

    adapter = RestCRMAdapter(
        base_url="http://crm.internal",
        client=mock_client,
        fallback_to_default=False,
    )

    profile = await adapter.get_user_profile("user-rest-1")
    assert profile is not None
    assert profile.name == "Bob Martin"
    assert profile.preferred_brands.get("cheese") == "Tillamook"

    orders = await adapter.get_past_orders("user-rest-1")
    assert len(orders) == 1
    assert orders[0].order_id == "ord-rest-101"

    context = await adapter.get_user_context("user-rest-1")
    assert context.user_profile.name == "Bob Martin"
    assert len(context.past_orders) == 1

    await adapter.close()


@pytest.mark.asyncio
async def test_rest_crm_adapter_combined_context_endpoint():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False

    context_data = {
        "user_profile": {
            "user_id": "user-context-1",
            "name": "Charlie",
            "preferred_brands": {"tea": "Twinings"},
        },
        "past_orders": [
            {
                "order_id": "ord-ctx-1",
                "items": [
                    {
                        "sku_id": "sku-tea-1",
                        "name": "Twinings Earl Grey",
                        "quantity": 1.0,
                        "unit_price": 3.99,
                    }
                ],
                "total_amount": 3.99,
            }
        ],
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = context_data
    mock_client.get.return_value = mock_resp

    adapter = RestCRMAdapter(client=mock_client)
    context = await adapter.get_user_context("user-context-1")

    assert context.user_profile.user_id == "user-context-1"
    assert context.user_profile.name == "Charlie"
    assert context.past_orders[0].order_id == "ord-ctx-1"

    await adapter.close()


@pytest.mark.asyncio
async def test_rest_crm_adapter_network_and_404_fallbacks():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False

    # 404 response
    mock_404_resp = MagicMock()
    mock_404_resp.status_code = 404
    mock_client.get.return_value = mock_404_resp

    # Adapter with fallback_to_default=True
    adapter_fallback = RestCRMAdapter(client=mock_client, fallback_to_default=True)
    profile = await adapter_fallback.get_user_profile("nonexistent-user")
    assert profile is not None
    assert profile.name == "Guest User"

    # Adapter with fallback_to_default=False
    adapter_strict = RestCRMAdapter(client=mock_client, fallback_to_default=False)
    strict_profile = await adapter_strict.get_user_profile("nonexistent-user")
    assert strict_profile is None

    # Request error / connection error handling
    mock_client.get.side_effect = httpx.RequestError("Connection timeout")
    with pytest.raises(CRMConnectionError):
        await adapter_strict.get_user_profile("error-user")

    await adapter_fallback.close()
    await adapter_strict.close()
