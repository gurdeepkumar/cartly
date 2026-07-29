from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class IntentActionEnum(str, Enum):
    ADD = "ADD"
    REMOVE = "REMOVE"
    MODIFY_QUANTITY = "MODIFY_QUANTITY"
    SUBSTITUTE = "SUBSTITUTE"
    CLARIFY = "CLARIFY"


class ChatMessage(BaseModel):
    role: str = Field(
        description="Role of message sender: 'user', 'assistant', or 'system'"
    )
    content: str = Field(description="Text content of the message")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when message was created",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional arbitrary metadata associated with the message",
    )


class SKU(BaseModel):
    id: str = Field(description="Unique identifier for the SKU")
    name: str = Field(description="Display name of the product")
    category: Optional[str] = Field(default=None, description="Product category")
    price: float = Field(ge=0.0, description="Unit price of the product")
    in_stock: bool = Field(default=True, description="Stock availability status")
    unit: str = Field(
        default="unit", description="Measurement unit (e.g., 'unit', 'kg', 'pack')"
    )
    brand: Optional[str] = Field(default=None, description="Brand name")
    attributes: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional attributes (e.g. dietary flags, weight)",
    )


class CartItem(BaseModel):
    sku: SKU = Field(description="SKU object associated with the cart item")
    quantity: float = Field(
        gt=0.0, default=1.0, description="Quantity of items in cart"
    )
    price_per_unit: float = Field(
        ge=0.0, description="Price per unit at the time of adding"
    )
    notes: Optional[str] = Field(
        default=None, description="Special notes or substitution info"
    )

    @model_validator(mode="before")
    @classmethod
    def set_default_price_per_unit(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "price_per_unit" not in data or data["price_per_unit"] is None:
                sku = data.get("sku")
                if isinstance(sku, dict) and "price" in sku:
                    data["price_per_unit"] = sku["price"]
                elif hasattr(sku, "price"):
                    data["price_per_unit"] = sku.price
        return data

    @property
    def total_price(self) -> float:
        return round(self.quantity * self.price_per_unit, 2)


class ShoppingBasket(BaseModel):
    items: List[CartItem] = Field(
        default_factory=list, description="List of items in the basket"
    )
    currency: str = Field(default="USD", description="Currency ISO code")
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of last basket modification",
    )

    @property
    def total_amount(self) -> float:
        return round(sum(item.total_price for item in self.items), 2)

    @property
    def item_count(self) -> int:
        return len(self.items)


class PendingClarification(BaseModel):
    id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for the clarification request",
    )
    question: str = Field(description="Clarifying question posed to the user")
    options: List[str] = Field(
        default_factory=list,
        description="Suggested choices or options for resolution",
    )
    target_item: Optional[str] = Field(
        default=None,
        description="Item or product query requiring clarification",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Reason why clarification is required (e.g. out of stock, multiple matches)",
    )


class ParsedIntent(BaseModel):
    action: IntentActionEnum = Field(description="Resolved action type")
    query: Optional[str] = Field(
        default=None, description="Raw query phrase or item description"
    )
    extracted_items: List[str] = Field(
        default_factory=list,
        description="List of product entity names extracted from user input",
    )
    target_sku_id: Optional[str] = Field(
        default=None, description="Resolved target SKU ID if applicable"
    )
    quantity: Optional[float] = Field(
        default=1.0, description="Quantity specified in intent"
    )
    clarify_reason: Optional[str] = Field(
        default=None, description="Explanation if clarification is needed"
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Confidence score of intent extraction"
    )


class ChatSession(BaseModel):
    session_id: str = Field(description="Unique multi-turn conversation session ID")
    user_id: str = Field(description="User identifier")
    history: List[ChatMessage] = Field(
        default_factory=list, description="Full conversation history"
    )
    basket: ShoppingBasket = Field(
        default_factory=ShoppingBasket, description="Current shopping basket state"
    )
    pending_clarification: Optional[PendingClarification] = Field(
        default=None,
        description="Active pending clarification if waiting for user resolution",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Session creation timestamp",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Session last update timestamp",
    )


class ChatRequest(BaseModel):
    session_id: str = Field(description="Session ID for the conversation")
    user_id: str = Field(description="User ID sending the message")
    message: str = Field(
        min_length=1, description="User natural language message content"
    )


class ChatResponse(BaseModel):
    session_id: str = Field(description="Session ID for the conversation")
    message: str = Field(description="Assistant response content")
    basket: ShoppingBasket = Field(description="Updated shopping basket state")
    pending_clarification: Optional[PendingClarification] = Field(
        default=None, description="Pending clarification if further info is needed"
    )
    actions_taken: List[str] = Field(
        default_factory=list,
        description="Summary of system actions executed during turn processing",
    )
