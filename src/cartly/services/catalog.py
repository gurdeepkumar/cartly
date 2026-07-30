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
