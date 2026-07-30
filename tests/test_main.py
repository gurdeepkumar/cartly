import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from cartly.main import app
from cartly.models.schemas import (
    ChatResponse,
    ChatSession,
    ShoppingBasket,
    CheckoutHandshakeResponse,
    CheckoutPayload,
)

client = TestClient(app)


@pytest.fixture
def mock_session():
    return ChatSession(
        session_id="test-session",
        user_id="test-user",
        history=[],
        basket=ShoppingBasket(items=[]),
    )


def test_health_check():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("cartly.services.workflow.CartlyWorkflowEngine.process_turn")
def test_process_chat_message(mock_process_turn):
    # Setup mock
    mock_response = ChatResponse(
        session_id="test-session",
        message="I've added milk to your basket.",
        basket=ShoppingBasket(items=[]),
        actions_taken=["Added Milk"],
    )
    mock_process_turn.return_value = mock_response

    # Call endpoint
    payload = {
        "session_id": "test-session",
        "user_id": "test-user",
        "message": "Add milk",
    }
    response = client.post("/api/v1/chat/message", json=payload)

    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "test-session"
    assert "milk" in data["message"]
    mock_process_turn.assert_called_once()


@patch("cartly.services.session.InMemorySessionStore.get_session")
def test_get_session_state_found(mock_get_session, mock_session):
    mock_get_session.return_value = mock_session

    response = client.get("/api/v1/chat/session/test-session")

    assert response.status_code == 200
    assert response.json()["session_id"] == "test-session"


def test_get_session_state_not_found():
    with patch(
        "cartly.services.session.InMemorySessionStore.get_session", return_value=None
    ):
        response = client.get("/api/v1/chat/session/non-existent")
        assert response.status_code == 404
        assert "not found" in response.json()["error"].lower()


@patch("cartly.services.checkout.CheckoutService.process_handshake")
def test_checkout_handshake(mock_process_handshake):
    # Setup mock
    mock_response = CheckoutHandshakeResponse(
        success=True,
        checkout_payload=CheckoutPayload(
            session_id="test-session",
            user_id="test-user",
            items=[],
            total_items=0,
            total_amount=0.0,
        ),
        message="Checkout ready",
    )
    mock_process_handshake.return_value = mock_response

    # Call endpoint
    payload = {
        "session_id": "test-session",
        "user_id": "test-user",
        "store_id": "target-store",
    }
    response = client.post("/api/v1/checkout/handshake", json=payload)

    # Assertions
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["message"] == "Checkout ready"


def test_error_handling_validation():
    # Invalid payload (missing message)
    payload = {"session_id": "test-session", "user_id": "test-user"}
    response = client.post("/api/v1/chat/message", json=payload)
    assert response.status_code == 422  # FastAPI built-in validation
