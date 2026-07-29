import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.cartly.models.schemas import (
    CartItem,
    ChatMessage,
    IntentActionEnum,
    ParsedIntent,
    SKU,
    ShoppingBasket,
)
from src.cartly.services.intent import LiteLLMIntentParser


@pytest.fixture
def sample_basket():
    sku = SKU(id="sku_001", name="Organic Milk", price=3.99, in_stock=True)
    item = CartItem(sku=sku, quantity=2.0, price_per_unit=3.99)
    return ShoppingBasket(items=[item])


@pytest.fixture
def sample_history():
    return [
        ChatMessage(role="user", content="Hi, I want to buy groceries."),
        ChatMessage(role="assistant", content="Sure! What would you like to add?"),
    ]


@pytest.mark.asyncio
async def test_aparse_intent_add_success():
    parser = LiteLLMIntentParser(model="gpt-4o-mini")
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps(
                    {
                        "action": "ADD",
                        "query": "add 2 gallons of milk",
                        "extracted_items": ["milk"],
                        "target_sku_id": None,
                        "quantity": 2.0,
                        "clarify_reason": None,
                        "confidence": 0.95,
                    }
                )
            )
        )
    ]

    with patch(
        "src.cartly.services.intent.acompletion",
        new=AsyncMock(return_value=mock_response),
    ):
        intent = await parser.aparse_intent("add 2 gallons of milk")
        assert intent.action == IntentActionEnum.ADD
        assert intent.extracted_items == ["milk"]
        assert intent.quantity == 2.0
        assert intent.confidence == 0.95


def test_parse_intent_sync_success():
    parser = LiteLLMIntentParser(model="gpt-4o-mini")
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps(
                    {
                        "action": "REMOVE",
                        "query": "remove apples",
                        "extracted_items": ["apples"],
                        "target_sku_id": "sku_123",
                        "quantity": 1.0,
                        "clarify_reason": None,
                        "confidence": 0.9,
                    }
                )
            )
        )
    ]

    with patch("src.cartly.services.intent.completion", return_value=mock_response):
        intent = parser.parse_intent("remove apples")
        assert intent.action == IntentActionEnum.REMOVE
        assert intent.extracted_items == ["apples"]
        assert intent.target_sku_id == "sku_123"


@pytest.mark.asyncio
async def test_aparse_intent_model_fallback_chain():
    parser = LiteLLMIntentParser(
        model="primary-failing-model", fallback_models=["fallback-working-model"]
    )

    mock_fallback_response = MagicMock()
    mock_fallback_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps(
                    {
                        "action": "MODIFY_QUANTITY",
                        "query": "change milk to 5",
                        "extracted_items": ["milk"],
                        "target_sku_id": None,
                        "quantity": 5.0,
                        "clarify_reason": None,
                        "confidence": 0.88,
                    }
                )
            )
        )
    ]

    async def mock_acompletion(*args, **kwargs):
        if kwargs.get("model") == "primary-failing-model":
            raise RuntimeError("Primary model API error")
        return mock_fallback_response

    with patch("src.cartly.services.intent.acompletion", side_effect=mock_acompletion):
        intent = await parser.aparse_intent("change milk to 5")
        assert intent.action == IntentActionEnum.MODIFY_QUANTITY
        assert intent.quantity == 5.0


@pytest.mark.asyncio
async def test_aparse_intent_all_llms_fail_heuristic_fallback():
    parser = LiteLLMIntentParser(
        model="failing-model-1", fallback_models=["failing-model-2"]
    )

    with patch(
        "src.cartly.services.intent.acompletion",
        side_effect=RuntimeError("All APIs down"),
    ):
        intent = await parser.aparse_intent("add 3 bananas")
        assert intent.action == IntentActionEnum.ADD
        assert intent.extracted_items == ["bananas"]
        assert intent.quantity == 3.0
        assert intent.confidence == 0.6


def test_heuristic_fallback_actions():
    parser = LiteLLMIntentParser()

    # ADD
    intent_add = parser._fallback_heuristic_parse("add 4 oranges")
    assert intent_add.action == IntentActionEnum.ADD
    assert intent_add.quantity == 4.0
    assert "oranges" in intent_add.extracted_items[0]

    # REMOVE
    intent_remove = parser._fallback_heuristic_parse("remove bread")
    assert intent_remove.action == IntentActionEnum.REMOVE
    assert "bread" in intent_remove.extracted_items[0]

    # MODIFY_QUANTITY
    intent_modify = parser._fallback_heuristic_parse("change quantity of milk to 3")
    assert intent_modify.action == IntentActionEnum.MODIFY_QUANTITY
    assert intent_modify.quantity == 3.0

    # SUBSTITUTE
    intent_sub = parser._fallback_heuristic_parse("substitute butter with margarine")
    assert intent_sub.action == IntentActionEnum.SUBSTITUTE
    assert intent_sub.extracted_items == ["butter", "margarine"]

    # CLARIFY (unknown prompt)
    intent_clarify = parser._fallback_heuristic_parse("what time is it?")
    assert intent_clarify.action == IntentActionEnum.CLARIFY
    assert intent_clarify.clarify_reason is not None


def test_build_prompt_messages_with_context(sample_basket, sample_history):
    parser = LiteLLMIntentParser()
    messages = parser._build_prompt_messages(
        user_message="Add 2 apples",
        history=sample_history,
        current_basket=sample_basket,
    )

    assert len(messages) == 3
    assert messages[0]["role"] == "system"
    assert "Organic Milk" in messages[1]["content"]
    assert "Hi, I want to buy groceries." in messages[1]["content"]
    assert messages[2]["content"] == "Add 2 apples"
