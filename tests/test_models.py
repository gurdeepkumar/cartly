from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from src.cartly.models import (
    SKU,
    CartItem,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatSession,
    IntentActionEnum,
    ParsedIntent,
    PendingClarification,
    ShoppingBasket,
)


def test_intent_action_enum():
    assert IntentActionEnum.ADD == "ADD"
    assert IntentActionEnum.REMOVE == "REMOVE"
    assert IntentActionEnum.MODIFY_QUANTITY == "MODIFY_QUANTITY"
    assert IntentActionEnum.SUBSTITUTE == "SUBSTITUTE"
    assert IntentActionEnum.CLARIFY == "CLARIFY"


def test_sku_creation_and_defaults():
    sku = SKU(
        id="sku-101",
        name="Whole Organic Milk 1L",
        category="Dairy",
        price=2.99,
        brand="FarmFresh",
    )
    assert sku.id == "sku-101"
    assert sku.name == "Whole Organic Milk 1L"
    assert sku.price == 2.99
    assert sku.in_stock is True
    assert sku.unit == "unit"
    assert sku.attributes == {}


def test_sku_negative_price_validation():
    with pytest.raises(ValidationError):
        SKU(id="sku-invalid", name="Invalid", price=-1.5)


def test_cart_item_and_total_price():
    sku = SKU(id="sku-101", name="Organic Milk", price=2.50)
    cart_item = CartItem(sku=sku, quantity=3.0)

    assert cart_item.price_per_unit == 2.50
    assert cart_item.total_price == 7.50


def test_cart_item_custom_price_per_unit():
    sku = SKU(id="sku-101", name="Organic Milk", price=3.00)
    cart_item = CartItem(sku=sku, quantity=2.0, price_per_unit=2.50)

    assert cart_item.price_per_unit == 2.50
    assert cart_item.total_price == 5.00


def test_shopping_basket_totals():
    sku1 = SKU(id="sku-101", name="Milk", price=2.50)
    sku2 = SKU(id="sku-102", name="Bread", price=1.50)

    basket = ShoppingBasket(
        items=[
            CartItem(sku=sku1, quantity=2.0),
            CartItem(sku=sku2, quantity=1.0),
        ]
    )

    assert basket.item_count == 2
    assert basket.total_amount == 6.50


def test_pending_clarification_defaults():
    clarification = PendingClarification(
        question="Did you mean 1L or 2L milk?",
        options=["1L Whole Milk", "2L Whole Milk"],
        target_item="milk",
    )
    assert clarification.id is not None
    assert len(clarification.options) == 2


def test_parsed_intent_creation():
    intent = ParsedIntent(
        action=IntentActionEnum.ADD,
        query="add 2 cartons of organic milk",
        extracted_items=["organic milk"],
        quantity=2.0,
        confidence=0.95,
    )
    assert intent.action == IntentActionEnum.ADD
    assert intent.quantity == 2.0
    assert intent.confidence == 0.95


def test_chat_session_history_and_state():
    msg1 = ChatMessage(role="user", content="I need some eggs and milk.")
    msg2 = ChatMessage(role="assistant", content="Added eggs and milk to your basket.")

    session = ChatSession(
        session_id="session-abc-123",
        user_id="user-456",
        history=[msg1, msg2],
    )

    assert session.session_id == "session-abc-123"
    assert len(session.history) == 2
    assert session.basket.total_amount == 0.0
    assert session.pending_clarification is None


def test_chat_request_and_response_schemas():
    req = ChatRequest(
        session_id="sess-1",
        user_id="user-1",
        message="Please remove the bread.",
    )
    assert req.message == "Please remove the bread."

    resp = ChatResponse(
        session_id="sess-1",
        message="Removed bread from your cart.",
        basket=ShoppingBasket(),
        actions_taken=["REMOVED_SKU_102"],
    )
    assert resp.session_id == "sess-1"
    assert resp.actions_taken == ["REMOVED_SKU_102"]


def test_session_serialization_deserialization():
    sku = SKU(id="sku-200", name="Butter 250g", price=3.20)
    basket = ShoppingBasket(items=[CartItem(sku=sku, quantity=1.0)])
    msg = ChatMessage(role="user", content="Add butter")

    session = ChatSession(
        session_id="sess-test",
        user_id="user-test",
        history=[msg],
        basket=basket,
    )

    dumped = session.model_dump(mode="json")
    reconstituted = ChatSession.model_validate(dumped)

    assert reconstituted.session_id == session.session_id
    assert reconstituted.basket.total_amount == 3.20
    assert len(reconstituted.history) == 1
    assert reconstituted.history[0].content == "Add butter"
