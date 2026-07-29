# Cartly: Feature Specifications

## 1. Conversational Intent Processing
- Parse natural language requests containing weekly essentials, recipe descriptions, or cart modifications.
- Extract structured entities using explicit Pydantic schemas (product names, quantities, dietary attributes).
- Support explicit intent actions:
  - **Item Addition**: Add requested or inferred items to cart.
  - **Item Removal**: Remove specific items or SKUs from cart.
  - **Quantity Modification**: Increase, decrease, or update item quantities.
  - **Out-of-Stock Substitution**: Propose alternative SKUs when requested items are out of stock.

## 2. User Context Integration (CRM Engine)
- Retrieve past purchase history and brand loyalties for the active user.
- Automatically resolve generic product queries (e.g., "Milk") to preferred specific SKUs.

## 3. Real-Time Inventory & Catalog Mapping
- Search catalog for real-time SKU availability, pricing, and promotions.
- Perform recipe-to-SKU mapping (e.g., "spicy pasta" -> pasta, tomatoes, chili peppers).

## 4. Interactive Refinement & Clarifications
- Present structured shopping basket with direct matches and inferred items.
- Generate clarifying questions when items are ambiguous or out of stock.
- Handle sliding-window message buffer for multi-turn sessions with Redis-compatible session store.

## 5. Supermarket Handshake
- Export finalized shopping basket directly to supermarket checkout system via standardized API.
