from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest

from src.cartly.services.crm import (
    CRMConnectionError,
    RestCRMAdapter,
)


@pytest.mark.asyncio
async def test_rest_crm_adapter_success():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False

    profile_data = {
        "user_id": "user-123",
        "name": "Jane Doe",
        "email": "jane@example.com",
        "preferred_brands": {"milk": "Oatly"},
        "dietary_preferences": ["vegan"],
        "favorite_skus": ["sku-1"],
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = profile_data
    mock_client.get.return_value = mock_resp

    adapter = RestCRMAdapter(
        base_url="http://crm.internal", client=mock_client, fallback_to_default=False
    )

    profile = await adapter.get_user_profile("user-123")
    assert profile is not None
    assert profile.user_id == "user-123"
    assert profile.preferred_brands["milk"] == "Oatly"

    await adapter.close()


@pytest.mark.asyncio
async def test_rest_crm_adapter_connection_error():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False
    mock_client.get.side_effect = httpx.RequestError("Network down")

    adapter = RestCRMAdapter(client=mock_client, fallback_to_default=False)

    with pytest.raises(CRMConnectionError):
        await adapter.get_user_profile("user-123")

    await adapter.close()
