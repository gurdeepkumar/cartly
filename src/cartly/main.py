from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from typing import Dict, Any

from cartly.models.schemas import (
    ChatRequest,
    ChatResponse,
    ChatSession,
    CheckoutHandshakeRequest,
    CheckoutHandshakeResponse,
)
from cartly.services.workflow import CartlyWorkflowEngine
from cartly.services.session import InMemorySessionStore, BaseSessionStore
from cartly.services.checkout import CheckoutService

app = FastAPI(
    title="Cartly API",
    description="Multi-Turn Conversational Chat Engine for Grocery Shopping",
    version="1.0.0",
)


# Dependency Injection
def get_session_store() -> BaseSessionStore:
    # In production, this would be RedisSessionStore
    return InMemorySessionStore()


def get_workflow(
    session_store: BaseSessionStore = Depends(get_session_store),
) -> CartlyWorkflowEngine:
    return CartlyWorkflowEngine(session_store=session_store)


def get_checkout_service(
    session_store: BaseSessionStore = Depends(get_session_store),
) -> CheckoutService:
    return CheckoutService(session_store=session_store)


# Exception Handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "message": str(exc),
            "status_code": 500,
        },
    )


# Endpoints
@app.post("/api/v1/chat/message", response_model=ChatResponse, tags=["Chat"])
async def process_chat_message(
    request: ChatRequest, workflow: CartlyWorkflowEngine = Depends(get_workflow)
):
    """
    Processes a natural language message from the user, updates the session,
    and returns a response with the current basket state.
    """
    try:
        response = await workflow.process_turn(
            session_id=request.session_id,
            user_id=request.user_id,
            message=request.message,
        )
        return response
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing chat message: {str(e)}",
        )


@app.get("/api/v1/chat/session/{session_id}", response_model=ChatSession, tags=["Chat"])
async def get_session_state(
    session_id: str, session_store: BaseSessionStore = Depends(get_session_store)
):
    """
    Retrieves the current state of a chat session including history and basket.
    """
    session = await session_store.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )
    return session


@app.post(
    "/api/v1/checkout/handshake",
    response_model=CheckoutHandshakeResponse,
    tags=["Checkout"],
)
async def checkout_handshake(
    request: CheckoutHandshakeRequest,
    checkout_service: CheckoutService = Depends(get_checkout_service),
):
    """
    Converts a chat session's basket into a supermarket checkout payload.
    """
    try:
        response = await checkout_service.process_handshake(request=request)
        return response
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Checkout handshake failed: {str(e)}",
        )


@app.get("/healthz", tags=["Infrastructure"])
async def health_check():
    return {"status": "ok"}
