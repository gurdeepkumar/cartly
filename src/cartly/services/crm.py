from abc import ABC, abstractmethod
from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional
import httpx

from src.cartly.config import settings
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CRMError(Exception):
    """Base exception for CRM operations."""

    pass


class UserNotFoundError(CRMError):
    """Raised when a user profile is not found in the CRM system."""

    pass


class CRMConnectionError(CRMError):
    """Raised when communicating with the external CRM service fails."""

    pass


class PastOrderItem(BaseModel):
    sku_id: str = Field(description="SKU identifier")
    name: str = Field(description="Product name")
    quantity: float = Field(default=1.0, gt=0.0, description="Quantity purchased")
    unit_price: float = Field(ge=0.0, description="Unit price at purchase time")


class PastOrder(BaseModel):
    order_id: str = Field(description="Unique order ID")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when order was placed",
    )
    items: List[PastOrderItem] = Field(
        default_factory=list, description="Items included in past order"
    )
    total_amount: float = Field(ge=0.0, description="Total amount for order")


class UserProfile(BaseModel):
    user_id: str = Field(description="Unique user ID")
    name: Optional[str] = Field(default=None, description="User full name")
    email: Optional[str] = Field(default=None, description="User email address")
    preferred_brands: Dict[str, str] = Field(
        default_factory=dict,
        description="Brand preferences mapped by category/product (e.g., {'milk': 'Oatly'})",
    )
    dietary_preferences: List[str] = Field(
        default_factory=list,
        description="Dietary preferences or restrictions (e.g. ['vegan', 'organic'])",
    )
    favorite_skus: List[str] = Field(
        default_factory=list, description="List of preferred/favorite SKU IDs"
    )


class UserContext(BaseModel):
    user_profile: UserProfile = Field(
        description="User profile metadata and preferences"
    )
    past_orders: List[PastOrder] = Field(
        default_factory=list, description="Recent order history for user"
    )


class UserContextProvider(ABC):
    """Abstract interface for CRM adapters providing user context and preferences."""

    @abstractmethod
    async def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        """Retrieve user profile metadata and preferences by user ID."""
        pass

    @abstractmethod
    async def get_preferred_brand(
        self, user_id: str, category_or_product: str
    ) -> Optional[str]:
        """Retrieve default brand preference for a given category or product."""
        pass

    @abstractmethod
    async def get_past_orders(self, user_id: str, limit: int = 5) -> List[PastOrder]:
        """Retrieve recent past orders for user."""
        pass

    @abstractmethod
    async def get_user_context(self, user_id: str) -> UserContext:
        """Retrieve combined user profile and past order history."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close open resources or network clients."""
        pass


class RestCRMAdapter(UserContextProvider):
    """HTTP-backed CRM adapter connecting to external CRM service with timeout and retry logic."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 5.0,
        fallback_to_default: bool = True,
    ):
        self.base_url = (base_url or settings.CRM_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.fallback_to_default = fallback_to_default
        self._client = client

    async def get_client(self) -> httpx.AsyncClient:
        is_closed = getattr(self._client, "is_closed", False)
        if isinstance(is_closed, bool) and is_closed:
            closed_flag = True
        else:
            closed_flag = False

        if self._client is None or closed_flag:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        client = await self.get_client()
        url = f"/users/{user_id}"
        try:
            response = await client.get(url)
            if response.status_code == 404:
                if self.fallback_to_default:
                    logger.warning(
                        f"User {user_id} not found on CRM HTTP endpoint ({url}); returning default fallback."
                    )
                    return UserProfile(user_id=user_id, name="Guest User")
                return None
            response.raise_for_status()
            data = response.json()
            return UserProfile.model_validate(data)
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP status error fetching CRM profile for {user_id}: {e}")
            if self.fallback_to_default:
                return UserProfile(user_id=user_id, name="Guest User")
            raise CRMError(f"HTTP error fetching profile for {user_id}: {e}") from e
        except (httpx.RequestError, Exception) as e:
            logger.error(f"Network error fetching CRM profile for {user_id}: {e}")
            if self.fallback_to_default:
                return UserProfile(user_id=user_id, name="Guest User")
            raise CRMConnectionError(
                f"CRM service connection error for {user_id}: {e}"
            ) from e

    async def get_preferred_brand(
        self, user_id: str, category_or_product: str
    ) -> Optional[str]:
        profile = await self.get_user_profile(user_id)
        if not profile:
            return None
        key = category_or_product.lower().strip()
        return profile.preferred_brands.get(key)

    async def get_past_orders(self, user_id: str, limit: int = 5) -> List[PastOrder]:
        client = await self.get_client()
        url = f"/users/{user_id}/orders"
        try:
            response = await client.get(url, params={"limit": limit})
            if response.status_code == 404:
                return []
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list):
                return [PastOrder.model_validate(item) for item in data]
            return []
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP status error fetching past orders for {user_id}: {e}")
            if self.fallback_to_default:
                return []
            raise CRMError(f"HTTP error fetching orders for {user_id}: {e}") from e
        except (httpx.RequestError, Exception) as e:
            logger.error(f"Network error fetching past orders for {user_id}: {e}")
            if self.fallback_to_default:
                return []
            raise CRMConnectionError(
                f"CRM service connection error for {user_id}: {e}"
            ) from e

    async def get_user_context(self, user_id: str) -> UserContext:
        client = await self.get_client()
        url = f"/users/{user_id}/context"
        try:
            response = await client.get(url)
            if response.status_code == 200:
                return UserContext.model_validate(response.json())
        except Exception as e:
            logger.debug(
                f"Combined context endpoint not available ({e}), falling back to separate calls."
            )

        # Fallback to fetching profile and orders separately
        profile = await self.get_user_profile(user_id)
        if not profile:
            if not self.fallback_to_default:
                raise UserNotFoundError(f"User {user_id} not found")
            profile = UserProfile(user_id=user_id, name="Guest User")
        orders = await self.get_past_orders(user_id)
        return UserContext(user_profile=profile, past_orders=orders)

    async def close(self) -> None:
        if self._client is not None:
            is_closed = getattr(self._client, "is_closed", False)
            if not (isinstance(is_closed, bool) and is_closed):
                if hasattr(self._client, "aclose"):
                    await self._client.aclose()
            self._client = None
