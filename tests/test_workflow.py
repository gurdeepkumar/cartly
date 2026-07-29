from unittest.mock import AsyncMock, patch
import pytest

from src.cartly.models.schemas import (
    IntentActionEnum,
    ParsedIntent,
)
from src.cartly.services.catalog import MockCatalogAdapter
from src.cartly.services.crm import MockCRMAdapter
from src.cartly.services.intent import LiteLLMIntentParser
from src.cartly.services.session import InMemorySessionStore
from src.cartly.services.workflow import CartlyWorkflowEngine


@pytest.fixture
def workflow_engine():
    session_store = InMemorySessionStore()
    crm_adapter = MockCRMAdapter()
    catalog_adapter = MockCatalogAdapter()
    intent_parser = LiteLLMIntentParser()
    return CartlyWorkflowEngine(
        session_store=session_store,
        crm_adapter=crm_adapter,
        catalog_adapter=catalog_adapter,
        intent_parser=intent_parser,
    )


@pytest.mark.asyncio
async def test_process_turn_add_item(workflow_engine):
    mock_intent = ParsedIntent(
        action=IntentActionEnum.ADD,
        query="add bread",
        extracted_items=["bread"],
        quantity=2.0,
        confidence=0.9,
    )

    with patch.object(
        workflow_engine.intent_parser,
        "aparse_intent",
        new=AsyncMock(return_value=mock_intent),
    ):
        response = await workflow_engine.process_turn(
            session_id="session-001",
            user_id="user-123",
            message="Add 2 loaves of bread",
        )

        assert response.session_id == "session-001"
        assert response.basket.item_count == 1
        assert response.basket.items[0].sku.id == "sku-bread-001"
        assert response.basket.items[0].quantity == 2.0
        assert response.pending_clarification is None
        assert len(response.actions_taken) > 0


@pytest.mark.asyncio
async def test_process_turn_crm_preference(workflow_engine):
    # User user-123 has preferred brand 'Oatly' for 'milk'
    mock_intent = ParsedIntent(
        action=IntentActionEnum.ADD,
        query="add milk",
        extracted_items=["milk"],
        quantity=1.0,
        confidence=0.9,
    )

    with patch.object(
        workflow_engine.intent_parser,
        "aparse_intent",
        new=AsyncMock(return_value=mock_intent),
    ):
        response = await workflow_engine.process_turn(
            session_id="session-002",
            user_id="user-123",
            message="Add milk",
        )

        assert response.basket.item_count == 1
        assert "Oatly" in response.basket.items[0].sku.name


@pytest.mark.asyncio
async def test_process_turn_recipe_resolution(workflow_engine):
    mock_intent = ParsedIntent(
        action=IntentActionEnum.ADD,
        query="spaghetti carbonara",
        extracted_items=["spaghetti carbonara"],
        quantity=1.0,
        confidence=0.95,
    )

    with patch.object(
        workflow_engine.intent_parser,
        "aparse_intent",
        new=AsyncMock(return_value=mock_intent),
    ):
        response = await workflow_engine.process_turn(
            session_id="session-003",
            user_id="user-123",
            message="I want to make spaghetti carbonara",
        )

        assert response.basket.item_count == 4
        sku_names = [item.sku.name for item in response.basket.items]
        assert any("Spaghetti" in name for name in sku_names)
        assert any("Bacon" in name for name in sku_names)


@pytest.mark.asyncio
async def test_process_turn_out_of_stock_substitution(workflow_engine):
    # 'sku-eggs-001' is out of stock in MockCatalogAdapter, should auto-substitute to 'sku-eggs-002'
    mock_intent = ParsedIntent(
        action=IntentActionEnum.ADD,
        query="add eggs",
        extracted_items=["Large Grade A Eggs 12ct"],
        target_sku_id="sku-eggs-001",
        quantity=1.0,
        confidence=0.95,
    )

    with patch.object(
        workflow_engine.intent_parser,
        "aparse_intent",
        new=AsyncMock(return_value=mock_intent),
    ):
        response = await workflow_engine.process_turn(
            session_id="session-004",
            user_id="user-123",
            message="Add eggs",
        )

        assert response.basket.item_count == 1
        sub_item = response.basket.items[0]
        assert sub_item.sku.id == "sku-eggs-002"
        assert "Substituted" in sub_item.notes


@pytest.mark.asyncio
async def test_process_turn_remove_item(workflow_engine):
    # First turn: Add bread
    mock_intent_add = ParsedIntent(
        action=IntentActionEnum.ADD,
        query="add bread",
        extracted_items=["bread"],
        quantity=1.0,
    )
    with patch.object(
        workflow_engine.intent_parser,
        "aparse_intent",
        new=AsyncMock(return_value=mock_intent_add),
    ):
        await workflow_engine.process_turn("session-005", "user-123", "Add bread")

    # Second turn: Remove bread
    mock_intent_remove = ParsedIntent(
        action=IntentActionEnum.REMOVE,
        query="remove bread",
        extracted_items=["bread"],
        quantity=1.0,
    )
    with patch.object(
        workflow_engine.intent_parser,
        "aparse_intent",
        new=AsyncMock(return_value=mock_intent_remove),
    ):
        response = await workflow_engine.process_turn(
            "session-005", "user-123", "Remove bread"
        )
        assert response.basket.item_count == 0


@pytest.mark.asyncio
async def test_process_turn_modify_quantity(workflow_engine):
    # First turn: Add bread (qty 1)
    mock_intent_add = ParsedIntent(
        action=IntentActionEnum.ADD,
        query="add bread",
        extracted_items=["bread"],
        quantity=1.0,
    )
    with patch.object(
        workflow_engine.intent_parser,
        "aparse_intent",
        new=AsyncMock(return_value=mock_intent_add),
    ):
        await workflow_engine.process_turn("session-006", "user-123", "Add bread")

    # Second turn: Modify quantity to 5
    mock_intent_modify = ParsedIntent(
        action=IntentActionEnum.MODIFY_QUANTITY,
        query="change bread to 5",
        extracted_items=["bread"],
        quantity=5.0,
    )
    with patch.object(
        workflow_engine.intent_parser,
        "aparse_intent",
        new=AsyncMock(return_value=mock_intent_modify),
    ):
        response = await workflow_engine.process_turn(
            "session-006", "user-123", "Change bread to 5"
        )
        assert response.basket.items[0].quantity == 5.0


@pytest.mark.asyncio
async def test_process_turn_clarify_action(workflow_engine):
    mock_intent = ParsedIntent(
        action=IntentActionEnum.CLARIFY,
        query="what is the weather",
        clarify_reason="I did not understand which grocery item you wanted.",
    )

    with patch.object(
        workflow_engine.intent_parser,
        "aparse_intent",
        new=AsyncMock(return_value=mock_intent),
    ):
        response = await workflow_engine.process_turn(
            session_id="session-007",
            user_id="user-123",
            message="What is the weather today?",
        )

        assert response.pending_clarification is not None
        assert "did not understand" in response.pending_clarification.question
