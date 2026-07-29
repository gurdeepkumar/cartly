from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from src.cartly.models.schemas import SKU
from src.cartly.services.catalog import (
    CatalogConnectionError,
    CatalogError,
    MockCatalogAdapter,
    Recipe,
    RecipeIngredient,
    RestCatalogAdapter,
)


@pytest.mark.asyncio
async def test_mock_catalog_adapter_seeded_skus_and_search():
    adapter = MockCatalogAdapter()

    # Get SKU by ID
    milk = await adapter.get_sku("sku-milk-001")
    assert milk is not None
    assert milk.id == "sku-milk-001"
    assert milk.name == "Oatly Oat Milk 64oz"
    assert milk.price == 4.99
    assert milk.in_stock is True

    # Search SKUs by text
    search_res = await adapter.search_skus("milk")
    assert len(search_res) >= 2
    sku_ids = [s.id for s in search_res]
    assert "sku-milk-001" in sku_ids
    assert "sku-milk-002" in sku_ids

    # Search with category filter
    dairy_res = await adapter.search_skus("", category="dairy")
    assert len(dairy_res) >= 3
    for sku in dairy_res:
        assert sku.category == "dairy"

    # Nonexistent SKU
    assert await adapter.get_sku("sku-nonexistent") is None

    await adapter.close()


@pytest.mark.asyncio
async def test_mock_catalog_adapter_stock_price_and_substitutes():
    adapter = MockCatalogAdapter()

    # Stock and price for in-stock item
    stock_info = await adapter.get_stock_and_price("sku-milk-001")
    assert stock_info is not None
    assert stock_info["in_stock"] is True
    assert stock_info["price"] == 4.99

    # Stock and price for out-of-stock item
    egg_info = await adapter.get_stock_and_price("sku-eggs-001")
    assert egg_info is not None
    assert egg_info["in_stock"] is False

    # Get explicit substitutes for out-of-stock item
    substitutes = await adapter.get_substitutes("sku-eggs-001")
    assert len(substitutes) == 1
    assert substitutes[0].id == "sku-eggs-002"
    assert substitutes[0].in_stock is True

    # Stock/price for nonexistent item
    assert await adapter.get_stock_and_price("sku-missing") is None

    await adapter.close()


@pytest.mark.asyncio
async def test_mock_catalog_adapter_recipe_resolution():
    adapter = MockCatalogAdapter()

    # Exact name lookup
    recipe = await adapter.get_recipe("Spaghetti Carbonara")
    assert recipe is not None
    assert recipe.recipe_id == "rec-carbonara-01"
    assert len(recipe.ingredients) == 4
    assert len(recipe.skus) == 4

    # Case-insensitive / substring lookup
    carbonara = await adapter.get_recipe("carbonara")
    assert carbonara is not None
    assert carbonara.recipe_id == "rec-carbonara-01"

    # Nonexistent recipe
    assert await adapter.get_recipe("sushi roll") is None

    await adapter.close()


@pytest.mark.asyncio
async def test_mock_catalog_adapter_custom_items_and_recipes():
    adapter = MockCatalogAdapter()

    # Add custom SKU
    custom_sku = SKU(
        id="sku-apple-101",
        name="Honeycrisp Apple",
        category="produce",
        price=1.29,
        in_stock=True,
    )
    adapter.add_sku(custom_sku)

    retrieved = await adapter.get_sku("sku-apple-101")
    assert retrieved is not None
    assert retrieved.name == "Honeycrisp Apple"

    # Add custom recipe
    custom_recipe = Recipe(
        recipe_id="rec-apple-pie-01",
        name="Apple Pie",
        ingredients=[
            RecipeIngredient(
                sku_id="sku-apple-101", name="Honeycrisp Apple", quantity=5.0
            )
        ],
        skus=[custom_sku],
    )
    adapter.add_recipe(custom_recipe)

    fetched_recipe = await adapter.get_recipe("apple pie")
    assert fetched_recipe is not None
    assert fetched_recipe.recipe_id == "rec-apple-pie-01"
    assert len(fetched_recipe.skus) == 1

    await adapter.close()


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
