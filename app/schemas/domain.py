from decimal import Decimal
from typing import Annotated, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict

# Strict type for SKU to ensure consistency across adapters
SKU = Annotated[
    str,
    Field(description="The unique identifier for a product in the supermarket system"),
]


class Product(BaseModel):
    """Basic metadata for a product."""

    model_config = ConfigDict(frozen=True)

    sku: SKU
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    brand: Optional[str] = None
    unit: str = Field(description="e.g., '1kg', '500ml', 'pack of 6'")


class InventoryItem(BaseModel):
    """Real-time availability and pricing for a product."""

    product: Product
    price: Decimal
    currency: str = "USD"
    is_available: bool = True
    stock_quantity: Optional[int] = None


class BasketItem(BaseModel):
    """An item within a user's shopping basket."""

    product: Product
    quantity: int = 1
    price_at_addition: Decimal


class Basket(BaseModel):
    """The collection of items a user intends to purchase."""

    items: List[BasketItem] = []

    @property
    def total_price(self) -> Decimal:
        return sum(
            (item.price_at_addition * item.quantity for item in item.items),
            Decimal("0.00"),
        )


class UserContext(BaseModel):
    """Historical and preferential data used for personalization."""

    user_id: str
    past_purchases: List[SKU] = Field(
        default_factory=list, description="List of SKUs bought previously"
    )
    preferences: Dict[str, str] = Field(
        default_factory=dict,
        description="Dietary or brand preferences (e.g. {'milk': 'organic'})",
    )
    loyalty_program_id: Optional[str] = None
