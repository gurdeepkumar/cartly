from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest

from src.cartly.services.catalog import (
    CatalogConnectionError,
    RestCatalogAdapter,
)


@pytest.mark.asyncio
async def test_rest_catalog_adapter_success_endpoints():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False

    sku_data = {
        "id": "sku-rest-001",
        "name": "Rest Coffee Beans",
        "category": "beverages",
        "price": 12.99,
        "in_stock": True,
        "unit": "bag",
    }

    mock_sku_resp = MagicMock()
    mock_sku_resp.status_code = 200
    mock_sku_resp.json.return_value = sku_data

    mock_search_resp = MagicMock()
    mock_search_resp.status_code = 200
    mock_search_resp.json.return_value = [sku_data]

    mock_stock_resp = MagicMock()
    mock_stock_resp.status_code = 200
    mock_stock_resp.json.return_value = {
        "sku_id": "sku-rest-001",
        "in_stock": True,
        "price": 12.99,
    }

    recipe_data = {
        "recipe_id": "rec-rest-01",
        "name": "Filter Coffee",
        "ingredients": [
            {
                "sku_id": "sku-rest-001",
                "name": "Rest Coffee Beans",
                "quantity": 1.0,
                "unit": "bag",
            }
        ],
        "skus": [sku_data],
    }
    mock_recipe_resp = MagicMock()
    mock_recipe_resp.status_code = 200
    mock_recipe_resp.json.return_value = recipe_data

    def client_request_side_effect(method, url, **kwargs):
        if url == "/skus/sku-rest-001":
            return mock_sku_resp
        elif url == "/skus":
            return mock_search_resp
        elif url == "/skus/sku-rest-001/stock":
            return mock_stock_resp
        elif url == "/recipes/coffee":
            return mock_recipe_resp
        raise ValueError(f"Unexpected endpoint: {url}")

    mock_client.request.side_effect = client_request_side_effect

    adapter = RestCatalogAdapter(base_url="http://catalog.internal", client=mock_client)

    # SKU Lookup
    sku = await adapter.get_sku("sku-rest-001")
    assert sku is not None
    assert sku.id == "sku-rest-001"
    assert sku.price == 12.99

    # Search SKUs
    search_results = await adapter.search_skus("coffee")
    assert len(search_results) == 1
    assert search_results[0].name == "Rest Coffee Beans"

    # Stock & Price check
    stock_info = await adapter.get_stock_and_price("sku-rest-001")
    assert stock_info is not None
    assert stock_info["in_stock"] is True

    # Recipe lookup
    recipe = await adapter.get_recipe("coffee")
    assert recipe is not None
    assert recipe.recipe_id == "rec-rest-01"

    await adapter.close()


@pytest.mark.asyncio
async def test_rest_catalog_adapter_404_and_connection_retries():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.is_closed = False

    # Mock 404 response
    mock_404_resp = MagicMock()
    mock_404_resp.status_code = 404
    mock_client.request.return_value = mock_404_resp

    adapter = RestCatalogAdapter(client=mock_client, retries=1)

    assert await adapter.get_sku("nonexistent") is None
    assert await adapter.search_skus("unknown") == []
    assert await adapter.get_stock_and_price("nonexistent") is None
    assert await adapter.get_substitutes("nonexistent") == []
    assert await adapter.get_recipe("nonexistent") is None

    # Connection error / timeout handling with retries
    mock_client.request.side_effect = httpx.RequestError("Connection timeout")
    with pytest.raises(CatalogConnectionError):
        await adapter.get_sku("error-sku")

    await adapter.close()
