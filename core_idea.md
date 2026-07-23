# Cartly: The Conversational Integration Layer for E-Grocery

## Core Essence
Cartly is an **AI-Agent Middleware** that bridges the gap between a supermarket's backend systems (Inventory & CRM) and the end-user. It transforms the traditional search-and-filter UI into a streamlined, conversational e-commerce experience that builds shopping baskets through natural language.
---

## The Value Proposition
Unlike generic chatbots, Cartly acts as a "Headless Shopping Assistant" that knows:
1. **The Store:** Real-time inventory, pricing, and stock levels.
2. **The User:** Past purchase history, brand loyalties, and dietary preferences.
3. **The Intent:** Converting vague requests ("stuff for tacos") into specific SKUs.
---

## Technical Architecture (The Integration)
Cartly does not replace existing platforms; it connects to them via two primary API rails:

### 1. User Context Engine (CRM Integration)
*   **Input:** Historical order data, saved "favorites," and frequent replacements.
*   **Outcome:** When a user says "Milk," Cartly defaults to the specific brand/size previously purchased, bypassing the need for manual selection.

### 2. Live Inventory Stream (Catalog Integration)
*   **Input:** Real-time SKU availability, current promotions, and pricing.
*   **Outcome:** Ensures that every item discussed in the chat is actually in stock and provides immediate price transparency.
---

## The Workflow

1.  **Ingestion:** User provides a list via text or voice (e.g., *"Get my weekly essentials and ingredients for a spicy pasta."*).
2.  **Resolution:**
    *   **Direct Match:** "Weekly essentials" are mapped to the user's purchase history.
    *   **Inference:** "Spicy pasta" triggers a recipe-to-SKU mapping logic.
3.  **Refinement:** Cartly presents a brief summary or asks 1-2 clarifying questions for new items.
4.  **Handshake:** Once confirmed, Cartly pushes the compiled basket directly into the supermarket's native checkout system via API.

---

## Target Users
*   **Retailers:** Who want to reduce friction and increase basket size without rebuilding their entire front-end.
*   **Consumers:** Who find current grocery apps tedious and want a "30-second shopping" experience.
