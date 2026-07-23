# Cartly: Project Execution Roadmap

## Phase 1: Foundation & Interface Definitions
- [ ] **1.1 Project Scaffolding**
    - Initialize Python 3.11+ environment.
    - Setup FastAPI boilerplate.
    - Create directory structure:
        - `app/adapters/`: Implementation of external system connectors.
        - `app/core/`: Business logic and workflow engine.
        - `app/schemas/`: Pydantic v2 models.
        - `app/services/`: Utilities like LiteLLM wrappers.
- [ ] **1.2 Core Domain Schemas**
    - Define `SKU`, `Product`, `Basket`, `UserContext`, and `InventoryItem` using Pydantic.
    - Ensure strict typing for SKU identifiers and pricing.
- [ ] **1.3 Abstract Base Classes (The Adapter Pattern)**
    - Define `BaseInventoryProvider` (search, get_price, check_stock).
    - Define `BaseUserContextProvider` (get_history, get_preferences).
- [ ] **1.4 LiteLLM Integration Layer**
    - Create a provider-agnostic `LLMService`.
    - Configure global exception handling for LLM timeouts/failures.

## Phase 2: LangGraph Workflow Design
- [ ] **2.1 State Definition**
    - Define `CartState` to track the basket, user identity, and conversational history.
- [ ] **2.2 Intent Parsing Node**
    - Map NL to actions: `ADD`, `REMOVE`, `QUERY`, `CHECKOUT`.
- [ ] **2.3 Resolution Node**
    - Implement logic to bridge NL "intent" to structured SKU lookups using the abstract adapters.
- [ ] **2.4 Refinement Node**
    - Logic for multi-turn loops when items are ambiguous (e.g., "Which fat percentage for the milk?").

## Phase 3: The Intelligence Layer (Context & Inference)
- [ ] **3.1 History-Aware Defaulting**
    - Logic to cross-reference `UserContext` when a generic item is requested.
- [ ] **3.2 Recipe-to-SKU Inference**
    - Implement system prompts (via LiteLLM) to expand high-level requests into lists of ingredients.
- [ ] **3.3 Validation & Price Transparency**
    - Post-inference validation to ensure all suggested items are `In Stock`.

## Phase 4: Adapter Implementations (The Bridge)
- [ ] **4.1 Mock Supermarket Adapter**
    - Concrete implementation for testing using local datasets.
- [ ] **4.2 Mock CRM Adapter**
    - Concrete implementation for testing user loyalty data.
- [ ] **4.3 Standardized Error Handling**
    - Implement custom HTTP exceptions (422 Mapping Failure, 503 Provider Timeout).

## Phase 5: FastAPI Delivery & Handshake
- [ ] **5.1 Conversational Endpoint**
    - `POST /chat`: The main entry point for the LLM-driven interaction.
- [ ] **5.2 Checkout Handshake**
    - `POST /checkout`: Final conversion of the internal state to the supermarket's native API format.
- [ ] **5.3 Integration Testing**
    - End-to-end test suite using mock adapters.