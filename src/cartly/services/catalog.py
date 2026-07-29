from abc import ABC, abstractmethod
import logging
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel, Field

from src.cartly.config import settings
from src.cartly.models.schemas import SKU

logger = logging.getLogger(__name__)


class CatalogError(Exception):
    """Base exception for catalog service operations."""

    pass


class SKUNotFoundError(CatalogError):
    """Raised when a specific SKU is not found in the catalog."""

    pass


class CatalogConnectionError(CatalogError):
    """Raised when communication with the external catalog service fails."""

    pass


class RecipeIngredient(BaseModel):
    sku_id: str = Field(description="Associated SKU identifier for the ingredient")
    name: str = Field(description="Ingredient display name")
    quantity: float = Field(default=1.0, gt=0.0, description="Quantity required")
    unit: str = Field(
        default="unit", description="Measurement unit (e.g., 'unit', 'g', 'oz')"
    )


class Recipe(BaseModel):
    recipe_id: str = Field(description="Unique identifier for the recipe")
    name: str = Field(description="Recipe name or title")
    description: Optional[str] = Field(
        default=None, description="Optional description or preparation steps"
    )
    servings: int = Field(default=4, gt=0, description="Number of servings")
    ingredients: List[RecipeIngredient] = Field(
        default_factory=list, description="List of recipe ingredients with quantities"
    )
    skus: List[SKU] = Field(
        default_factory=list,
        description="Resolved list of concrete SKU objects for recipe",
    )


class InventoryProvider(ABC):
    """Abstract interface for catalog and inventory management services."""

    @abstractmethod
    async def get_sku(self, sku_id: str) -> Optional[SKU]:
        """Retrieve detailed product information for a given SKU ID."""
        pass

    @abstractmethod
    async def search_skus(
        self, query: str, category: Optional[str] = None, limit: int = 10
    ) -> List[SKU]:
        """Search products by query phrase and optional category filter."""
        pass

    @abstractmethod
    async def get_stock_and_price(self, sku_id: str) -> Optional[Dict[str, Any]]:
        """Fetch current stock availability and pricing for a given SKU ID."""
        pass

    @abstractmethod
    async def get_substitutes(self, sku_id: str, limit: int = 3) -> List[SKU]:
        """Fetch recommended in-stock substitute SKUs for an out-of-stock item."""
        pass

    @abstractmethod
    async def get_recipe(self, recipe_name_or_id: str) -> Optional[Recipe]:
        """Resolve a recipe or bundle query to concrete ingredients and SKUs."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Release underlying HTTP clients or resources."""
        pass


class MockCatalogAdapter(InventoryProvider):
    """In-memory mock catalog adapter seeded with default products, stock, substitutes, and recipes."""

    def __init__(self, fallback_to_search: bool = True):
        self.fallback_to_search = fallback_to_search
        self._skus: Dict[str, SKU] = {}
        self._substitutes: Dict[str, List[str]] = {}
        self._recipes: Dict[str, Recipe] = {}
        self._seed_default_data()

    def _seed_default_data(self) -> None:
        """Seed initial inventory data for unit testing and local development."""
        default_skus = [
            SKU(
                id="sku-milk-001",
                name="Oatly Oat Milk 64oz",
                category="dairy",
                price=4.99,
                in_stock=True,
                brand="Oatly",
                unit="carton",
            ),
            SKU(
                id="sku-milk-002",
                name="Organic Valley Whole Milk 64oz",
                category="dairy",
                price=3.99,
                in_stock=True,
                brand="Organic Valley",
                unit="carton",
            ),
            SKU(
                id="sku-bread-001",
                name="Dave's Organic Whole Wheat Bread",
                category="bakery",
                price=5.49,
                in_stock=True,
                brand="Dave's Killer Bread",
                unit="loaf",
            ),
            SKU(
                id="sku-pasta-001",
                name="Barilla Spaghetti 16oz",
                category="pasta",
                price=1.99,
                in_stock=True,
                brand="Barilla",
                unit="box",
            ),
            SKU(
                id="sku-eggs-001",
                name="Large Grade A Eggs 12ct",
                category="dairy",
                price=3.49,
                in_stock=False,  # Out of stock to test substitution logic
                brand="Eggland's Best",
                unit="carton",
            ),
            SKU(
                id="sku-eggs-002",
                name="Organic Free Range Eggs 12ct",
                category="dairy",
                price=4.99,
                in_stock=True,
                brand="Vital Farms",
                unit="carton",
            ),
            SKU(
                id="sku-bacon-001",
                name="Thick Cut Applewood Smoked Bacon 12oz",
                category="meat",
                price=6.99,
                in_stock=True,
                brand="Oscar Mayer",
                unit="pack",
            ),
            SKU(
                id="sku-cheese-001",
                name="Parmigiano Reggiano Wedge 8oz",
                category="dairy",
                price=7.99,
                in_stock=True,
                brand="BelGioioso",
                unit="wedge",
            ),
            SKU(
                id="sku-guacamole-001",
                name="Fresh Guacamole 8oz",
                category="produce",
                price=3.99,
                in_stock=True,
                brand="Wholly Guacamole",
                unit="container",
            ),
        ]

        for sku in default_skus:
            self._skus[sku.id] = sku

        # Map out-of-stock eggs to organic eggs substitute
        self._substitutes["sku-eggs-001"] = ["sku-eggs-002"]

        # Seed Carbonara recipe
        carbonara = Recipe(
            recipe_id="rec-carbonara-01",
            name="Spaghetti Carbonara",
            description="Classic Italian pasta dish made with eggs, cheese, and bacon.",
            servings=4,
            ingredients=[
                RecipeIngredient(
                    sku_id="sku-pasta-001", name="Barilla Spaghetti 16oz", quantity=1.0
                ),
                RecipeIngredient(
                    sku_id="sku-eggs-002",
                    name="Organic Free Range Eggs 12ct",
                    quantity=1.0,
                ),
                RecipeIngredient(
                    sku_id="sku-bacon-001", name="Thick Cut Bacon 12oz", quantity=1.0
                ),
                RecipeIngredient(
                    sku_id="sku-cheese-001",
                    name="Parmigiano Reggiano 8oz",
                    quantity=1.0,
                ),
            ],
            skus=[
                self._skus["sku-pasta-001"],
                self._skus["sku-eggs-002"],
                self._skus["sku-bacon-001"],
                self._skus["sku-cheese-001"],
            ],
        )
        self._recipes["rec-carbonara-01"] = carbonara
        self._recipes["spaghetti carbonara"] = carbonara
        self._recipes["carbonara"] = carbonara

    def add_sku(self, sku: SKU) -> None:
        """Add or update a SKU in the mock database."""
        self._skus[sku.id] = sku

    def add_recipe(self, recipe: Recipe) -> None:
        """Add or update a recipe in the mock database."""
        self._recipes[recipe.recipe_id] = recipe
        self._recipes[recipe.name.lower().strip()] = recipe

    def set_substitutes(self, sku_id: str, substitute_ids: List[str]) -> None:
        """Configure explicit substitute mappings for a SKU."""
        self._substitutes[sku_id] = substitute_ids

    async def get_sku(self, sku_id: str) -> Optional[SKU]:
        return self._skus.get(sku_id)

    async def search_skus(
        self, query: str, category: Optional[str] = None, limit: int = 10
    ) -> List[SKU]:
        tokens = query.lower().split()
        results: List[SKU] = []

        for sku in self._skus.values():
            if category and sku.category and sku.category.lower() != category.lower():
                continue

            searchable_text = (
                f"{sku.name} {sku.brand or ''} {sku.category or ''}".lower()
            )
            if all(token in searchable_text for token in tokens):
                results.append(sku)

        return results[:limit]

    async def get_stock_and_price(self, sku_id: str) -> Optional[Dict[str, Any]]:
        sku = await self.get_sku(sku_id)
        if not sku:
            return None
        return {
            "sku_id": sku.id,
            "in_stock": sku.in_stock,
            "price": sku.price,
            "unit": sku.unit,
        }

    async def get_substitutes(self, sku_id: str, limit: int = 3) -> List[SKU]:
        sub_ids = self._substitutes.get(sku_id, [])
        substitutes: List[SKU] = []

        for sub_id in sub_ids:
            sku = await self.get_sku(sub_id)
            if sku and sku.in_stock:
                substitutes.append(sku)

        # Fallback to searching same category if no explicit substitutes found
        if not substitutes and self.fallback_to_search:
            target_sku = await self.get_sku(sku_id)
            if target_sku and target_sku.category:
                candidates = await self.search_skus("", category=target_sku.category)
                substitutes = [
                    cand for cand in candidates if cand.id != sku_id and cand.in_stock
                ]

        return substitutes[:limit]

    async def get_recipe(self, recipe_name_or_id: str) -> Optional[Recipe]:
        key = recipe_name_or_id.lower().strip()
        if key in self._recipes:
            return self._recipes[key]

        # Substring search for recipe
        for name, recipe in self._recipes.items():
            if key in name or name in key:
                return recipe

        return None

    async def close(self) -> None:
        self._skus.clear()
        self._substitutes.clear()
        self._recipes.clear()


class RestCatalogAdapter(InventoryProvider):
    """HTTP-backed catalog adapter connecting to external microservice with retry logic and timeouts."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 5.0,
        retries: int = 2,
    ):
        self.base_url = (base_url or settings.CATALOG_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self._client = client

    async def get_client(self) -> httpx.AsyncClient:
        is_closed = getattr(self._client, "is_closed", False)
        closed_flag = isinstance(is_closed, bool) and is_closed

        if self._client is None or closed_flag:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def _execute_with_retry(
        self, method: str, url: str, **kwargs
    ) -> httpx.Response:
        client = await self.get_client()
        last_exception: Optional[Exception] = None

        for attempt in range(self.retries + 1):
            try:
                response = await client.request(method, url, **kwargs)
                return response
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                last_exception = exc
                logger.warning(
                    f"Attempt {attempt + 1}/{self.retries + 1} failed for {url}: {exc}"
                )

        raise CatalogConnectionError(
            f"Catalog service call failed after {self.retries + 1} attempts on {url}: {last_exception}"
        ) from last_exception

    async def get_sku(self, sku_id: str) -> Optional[SKU]:
        url = f"/skus/{sku_id}"
        try:
            response = await self._execute_with_retry("GET", url)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return SKU.model_validate(response.json())
        except CatalogConnectionError:
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching SKU {sku_id}: {e}")
            raise CatalogError(f"HTTP status error for SKU {sku_id}: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error fetching SKU {sku_id}: {e}")
            raise CatalogError(f"Failed to fetch SKU {sku_id}: {e}") from e

    async def search_skus(
        self, query: str, category: Optional[str] = None, limit: int = 10
    ) -> List[SKU]:
        url = "/skus"
        params: Dict[str, Any] = {"query": query, "limit": limit}
        if category:
            params["category"] = category

        try:
            response = await self._execute_with_retry("GET", url, params=params)
            if response.status_code == 404:
                return []
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                return [SKU.model_validate(item) for item in data]
            return []
        except CatalogConnectionError:
            raise
        except Exception as e:
            logger.error(f"Error searching SKUs for query '{query}': {e}")
            raise CatalogError(f"Search failed for query '{query}': {e}") from e

    async def get_stock_and_price(self, sku_id: str) -> Optional[Dict[str, Any]]:
        url = f"/skus/{sku_id}/stock"
        try:
            response = await self._execute_with_retry("GET", url)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except CatalogConnectionError:
            raise
        except Exception as e:
            logger.error(f"Error checking stock/price for SKU {sku_id}: {e}")
            raise CatalogError(f"Stock/price check failed for SKU {sku_id}: {e}") from e

    async def get_substitutes(self, sku_id: str, limit: int = 3) -> List[SKU]:
        url = f"/skus/{sku_id}/substitutes"
        params = {"limit": limit}
        try:
            response = await self._execute_with_retry("GET", url, params=params)
            if response.status_code == 404:
                return []
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                return [SKU.model_validate(item) for item in data]
            return []
        except CatalogConnectionError:
            raise
        except Exception as e:
            logger.error(f"Error fetching substitutes for SKU {sku_id}: {e}")
            raise CatalogError(f"Substitutes fetch failed for SKU {sku_id}: {e}") from e

    async def get_recipe(self, recipe_name_or_id: str) -> Optional[Recipe]:
        url = f"/recipes/{recipe_name_or_id}"
        try:
            response = await self._execute_with_retry("GET", url)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return Recipe.model_validate(response.json())
        except CatalogConnectionError:
            raise
        except Exception as e:
            logger.error(f"Error fetching recipe '{recipe_name_or_id}': {e}")
            raise CatalogError(
                f"Recipe lookup failed for '{recipe_name_or_id}': {e}"
            ) from e

    async def close(self) -> None:
        if self._client is not None:
            is_closed = getattr(self._client, "is_closed", False)
            if not (isinstance(is_closed, bool) and is_closed):
                if hasattr(self._client, "aclose"):
                    await self._client.aclose()
            self._client = None
