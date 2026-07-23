# Cartly: Application Rules & Stack

## Tech Stack
- **Language**: Python 3.11+
- **Framework**: FastAPI
- **AI Orchestration**: LiteLLM (for model-agnostic LLM calls) + LangGraph (for workflow logic)
- **Validation**: Pydantic v2
- **Structure**: Monolithic (Single codebase containing core logic and all adapters)

## Architectural Focus: The Middleware Layer
- **Model Independence**: All LLM calls must go through an abstraction layer (LiteLLM). Hardcoding provider-specific libraries (like `openai` or `anthropic`) is forbidden in core logic.
- **Adapter Pattern**: The system defines abstract base classes for `InventoryProvider` and `UserContextProvider`. Concrete implementations for different supermarkets are stored within the monolith.
- **Unified Logic**: One deployment unit managing the bridge between NL intent and structured SKU output.

## Coding Rules
- **Schema Enforcement**: Define Pydantic models for every request/response. AI outputs must be validated against these schemas.
- **Abstraction Over Implementation**: Business logic must depend on abstractions (Interfaces), not concrete implementations of LLM providers or supermarket APIs.
- **Type Hinting**: Mandatory type hints for all function signatures.
- **Standardized Errors**: Use specific HTTP status codes (e.g., 422 for mapping failures, 503 for downstream adapter timeouts).
- **Naming**: Use `snake_case` for all Python code.
- **Testing**: Maintain a suite of mock adapters to test the monolith without calling live supermarket or LLM APIs.