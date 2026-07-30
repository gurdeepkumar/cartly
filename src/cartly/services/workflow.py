from typing import Any, Dict, List, Optional, TypedDict
import logging

from langgraph.graph import END, StateGraph

from src.cartly.config import settings
from src.cartly.models.schemas import (
    CartItem,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatSession,
    IntentActionEnum,
    ParsedIntent,
    PendingClarification,
    SKU,
    ShoppingBasket,
)
from src.cartly.services.catalog import (
    InventoryProvider,
    RestCatalogAdapter,
)
from src.cartly.services.crm import (
    UserContext,
    UserContextProvider,
    RestCRMAdapter,
)
from src.cartly.services.intent import LiteLLMIntentParser
from src.cartly.services.session import BaseSessionStore, RedisSessionStore

logger = logging.getLogger(__name__)


class CartlyState(TypedDict, total=False):
    """LangGraph state dict for multi-turn dialogue engine."""

    session_id: str
    user_id: str
    user_message: str
    session: ChatSession
    history: List[ChatMessage]
    basket: ShoppingBasket
    pending_clarification: Optional[PendingClarification]
    parsed_intent: Optional[ParsedIntent]
    user_context: Optional[UserContext]
    actions_taken: List[str]
    assistant_response: str


class CartlyWorkflowEngine:
    """LangGraph multi-turn dialogue workflow engine coordinating history, intent resolution,

    CRM context, inventory stock checking, substitution engine, and basket state management.
    """

    def __init__(
        self,
        session_store: Optional[BaseSessionStore] = None,
        crm_adapter: Optional[UserContextProvider] = None,
        catalog_adapter: Optional[InventoryProvider] = None,
        intent_parser: Optional[LiteLLMIntentParser] = None,
    ):
        self.session_store = session_store or RedisSessionStore()
        self.crm_adapter = crm_adapter or RestCRMAdapter()
        self.catalog_adapter = catalog_adapter or RestCatalogAdapter()
        self.intent_parser = intent_parser or LiteLLMIntentParser()
        self._graph = self._build_graph()

    def _build_graph(self):
        """Construct state graph with LangGraph node transitions."""
        builder = StateGraph(CartlyState)

        builder.add_node("history", self._history_node)
        builder.add_node("intent", self._intent_node)
        builder.add_node("crm_defaults", self._crm_defaults_node)
        builder.add_node("inventory_substitution", self._inventory_substitution_node)
        builder.add_node("basket_update", self._basket_update_node)

        builder.set_entry_point("history")
        builder.add_edge("history", "intent")
        builder.add_edge("intent", "crm_defaults")
        builder.add_edge("crm_defaults", "inventory_substitution")
        builder.add_edge("inventory_substitution", "basket_update")
        builder.add_edge("basket_update", END)

        return builder.compile()

    async def _history_node(self, state: CartlyState) -> CartlyState:
        """Fetch dialogue history and session state from session store."""
        session_id = state["session_id"]
        user_id = state["user_id"]
        user_message = state["user_message"]

        session = await self.session_store.get_session(session_id)
        if not session:
            session = ChatSession(session_id=session_id, user_id=user_id)

        user_msg = ChatMessage(role="user", content=user_message)
        session.history.append(user_msg)

        max_window = self.session_store.default_window_size
        if len(session.history) > max_window:
            session.history = session.history[-max_window:]

        actions = list(state.get("actions_taken", []))
        actions.append("Loaded dialogue history and active basket state")

        return {
            **state,
            "session": session,
            "history": list(session.history),
            "basket": session.basket.model_copy(deep=True),
            "pending_clarification": session.pending_clarification,
            "actions_taken": actions,
        }

    async def _intent_node(self, state: CartlyState) -> CartlyState:
        """Parse structured intent from user message using LiteLLM."""
        user_message = state["user_message"]
        history = state.get("history", [])
        basket = state.get("basket", ShoppingBasket())

        parsed_intent = await self.intent_parser.aparse_intent(
            user_message=user_message,
            history=history,
            current_basket=basket,
        )

        actions = list(state.get("actions_taken", []))
        actions.append(f"Parsed intent action: {parsed_intent.action.value}")

        return {
            **state,
            "parsed_intent": parsed_intent,
            "actions_taken": actions,
        }

    async def _crm_defaults_node(self, state: CartlyState) -> CartlyState:
        """Fetch CRM user profile context and default preferences."""
        user_id = state["user_id"]
        user_context = await self.crm_adapter.get_user_context(user_id)

        actions = list(state.get("actions_taken", []))
        actions.append("Retrieved user profile preferences and order history from CRM")

        return {
            **state,
            "user_context": user_context,
            "actions_taken": actions,
        }

    async def _inventory_substitution_node(self, state: CartlyState) -> CartlyState:
        """Check inventory stock, handle recipes, apply substitutions, and update basket items."""
        parsed_intent = state.get(
            "parsed_intent",
            ParsedIntent(action=IntentActionEnum.CLARIFY, query=state["user_message"]),
        )
        basket = state.get("basket", ShoppingBasket())
        user_context = state.get("user_context")
        user_id = state["user_id"]
        actions = list(state.get("actions_taken", []))
        pending_clarification = state.get("pending_clarification")

        items_list: List[CartItem] = list(basket.items)
        action_enum = parsed_intent.action

        if action_enum == IntentActionEnum.ADD:
            query = (
                parsed_intent.query
                or (
                    parsed_intent.extracted_items[0]
                    if parsed_intent.extracted_items
                    else ""
                )
            ).strip()

            # Check if query resolves to a recipe
            recipe = await self.catalog_adapter.get_recipe(query) if query else None
            if recipe:
                actions.append(f"Resolved recipe '{recipe.name}' from catalog")
                for ingredient_sku in recipe.skus:
                    if ingredient_sku.in_stock:
                        self._add_or_update_cart_item(
                            items_list, ingredient_sku, quantity=1.0
                        )
                        actions.append(
                            f"Added recipe item '{ingredient_sku.name}' to basket"
                        )
                    else:
                        substitutes = await self.catalog_adapter.get_substitutes(
                            ingredient_sku.id
                        )
                        if substitutes:
                            sub_sku = substitutes[0]
                            self._add_or_update_cart_item(
                                items_list,
                                sub_sku,
                                quantity=1.0,
                                notes=f"Substituted for out-of-stock {ingredient_sku.name}",
                            )
                            actions.append(
                                f"Substituted out-of-stock recipe item '{ingredient_sku.name}' with '{sub_sku.name}'"
                            )
                        else:
                            pending_clarification = PendingClarification(
                                question=f"Ingredient '{ingredient_sku.name}' for recipe '{recipe.name}' is out of stock and has no substitute.",
                                target_item=ingredient_sku.name,
                                reason="Out of stock",
                            )
                            actions.append(
                                f"Recipe item '{ingredient_sku.name}' out of stock without substitute"
                            )
            else:
                target_items = (
                    parsed_intent.extracted_items
                    if parsed_intent.extracted_items
                    else ([query] if query else [])
                )
                for item_phrase in target_items:
                    pref_brand = await self.crm_adapter.get_preferred_brand(
                        user_id, item_phrase
                    )
                    search_query = (
                        f"{pref_brand} {item_phrase}".strip()
                        if pref_brand
                        else item_phrase
                    )

                    candidate_skus = []
                    if parsed_intent.target_sku_id:
                        explicit_sku = await self.catalog_adapter.get_sku(
                            parsed_intent.target_sku_id
                        )
                        if explicit_sku:
                            candidate_skus.append(explicit_sku)

                    if not candidate_skus:
                        candidate_skus = await self.catalog_adapter.search_skus(
                            search_query
                        )
                        if not candidate_skus and pref_brand:
                            # Try search without brand prefix if strict brand search returned empty
                            candidate_skus = await self.catalog_adapter.search_skus(
                                item_phrase
                            )

                    if candidate_skus:
                        target_sku = candidate_skus[0]
                        requested_qty = parsed_intent.quantity or 1.0

                        if target_sku.in_stock:
                            self._add_or_update_cart_item(
                                items_list, target_sku, quantity=requested_qty
                            )
                            actions.append(
                                f"Added {requested_qty} x '{target_sku.name}' to basket"
                            )
                            pending_clarification = (
                                None  # Clear resolved pending clarification
                            )
                        else:
                            substitutes = await self.catalog_adapter.get_substitutes(
                                target_sku.id
                            )
                            if substitutes:
                                sub_sku = substitutes[0]
                                self._add_or_update_cart_item(
                                    items_list,
                                    sub_sku,
                                    quantity=requested_qty,
                                    notes=f"Substituted for out-of-stock {target_sku.name}",
                                )
                                actions.append(
                                    f"Substituted out-of-stock '{target_sku.name}' with '{sub_sku.name}'"
                                )
                            else:
                                pending_clarification = PendingClarification(
                                    question=f"'{target_sku.name}' is out of stock and no substitute was found. Would you like a different item?",
                                    target_item=target_sku.name,
                                    reason="Out of stock",
                                )
                                actions.append(
                                    f"Product '{target_sku.name}' out of stock without substitute"
                                )
                    else:
                        pending_clarification = PendingClarification(
                            question=f"Could not find any product matching '{item_phrase}'. Could you specify details?",
                            target_item=item_phrase,
                            reason="Product not found",
                        )
                        actions.append(f"No matching product found for '{item_phrase}'")

        elif action_enum == IntentActionEnum.REMOVE:
            target_items = (
                parsed_intent.extracted_items
                if parsed_intent.extracted_items
                else ([parsed_intent.query] if parsed_intent.query else [])
            )
            for item_phrase in target_items:
                matched_idx = self._find_basket_item_index(
                    items_list, item_phrase, parsed_intent.target_sku_id
                )
                if matched_idx is not None:
                    removed_item = items_list[matched_idx]
                    req_qty = parsed_intent.quantity or 1.0
                    if req_qty < removed_item.quantity:
                        removed_item.quantity -= req_qty
                        actions.append(
                            f"Reduced quantity of '{removed_item.sku.name}' by {req_qty}"
                        )
                    else:
                        items_list.pop(matched_idx)
                        actions.append(f"Removed '{removed_item.sku.name}' from basket")
                else:
                    actions.append(
                        f"Could not find item '{item_phrase}' in basket to remove"
                    )

        elif action_enum == IntentActionEnum.MODIFY_QUANTITY:
            target_items = (
                parsed_intent.extracted_items
                if parsed_intent.extracted_items
                else ([parsed_intent.query] if parsed_intent.query else [])
            )
            target_qty = (
                parsed_intent.quantity if parsed_intent.quantity is not None else 1.0
            )
            for item_phrase in target_items:
                matched_idx = self._find_basket_item_index(
                    items_list, item_phrase, parsed_intent.target_sku_id
                )
                if matched_idx is not None:
                    if target_qty <= 0:
                        removed_item = items_list.pop(matched_idx)
                        actions.append(f"Removed '{removed_item.sku.name}' from basket")
                    else:
                        items_list[matched_idx].quantity = target_qty
                        actions.append(
                            f"Updated quantity of '{items_list[matched_idx].sku.name}' to {target_qty}"
                        )
                else:
                    actions.append(
                        f"Could not find item '{item_phrase}' in basket to modify quantity"
                    )

        elif action_enum == IntentActionEnum.SUBSTITUTE:
            extracted = parsed_intent.extracted_items
            if len(extracted) >= 2:
                orig_name, new_name = extracted[0], extracted[1]
                matched_idx = self._find_basket_item_index(items_list, orig_name, None)
                if matched_idx is not None:
                    old_item = items_list.pop(matched_idx)
                    candidates = await self.catalog_adapter.search_skus(new_name)
                    if candidates and candidates[0].in_stock:
                        new_sku = candidates[0]
                        self._add_or_update_cart_item(
                            items_list, new_sku, quantity=old_item.quantity
                        )
                        actions.append(
                            f"Substituted '{old_item.sku.name}' with '{new_sku.name}'"
                        )
                    else:
                        pending_clarification = PendingClarification(
                            question=f"Could not find requested substitute '{new_name}' in stock.",
                            target_item=new_name,
                            reason="Substitute not found",
                        )
                        actions.append(
                            f"Failed to substitute '{old_item.sku.name}' with '{new_name}'"
                        )
                else:
                    actions.append(
                        f"Original item '{orig_name}' not found in basket for substitution"
                    )
            elif len(extracted) == 1 and items_list:
                item_name = extracted[0]
                matched_idx = self._find_basket_item_index(items_list, item_name, None)
                if matched_idx is not None:
                    target_item = items_list[matched_idx]
                    subs = await self.catalog_adapter.get_substitutes(
                        target_item.sku.id
                    )
                    if subs:
                        sub_sku = subs[0]
                        items_list.pop(matched_idx)
                        self._add_or_update_cart_item(
                            items_list,
                            sub_sku,
                            quantity=target_item.quantity,
                            notes=f"Substituted for {target_item.sku.name}",
                        )
                        actions.append(
                            f"Substituted '{target_item.sku.name}' with '{sub_sku.name}'"
                        )
                    else:
                        pending_clarification = PendingClarification(
                            question=f"No substitutes available for '{target_item.sku.name}'.",
                            target_item=target_item.sku.name,
                            reason="No substitutes",
                        )
                        actions.append(
                            f"No substitute found for '{target_item.sku.name}'"
                        )

        elif action_enum == IntentActionEnum.CLARIFY:
            pending_clarification = PendingClarification(
                question=parsed_intent.clarify_reason
                or "Could you please clarify your shopping request?",
                reason="Ambiguous request",
            )
            actions.append("Requested clarification from user")

        updated_basket = ShoppingBasket(items=items_list, currency=basket.currency)
        return {
            **state,
            "basket": updated_basket,
            "pending_clarification": pending_clarification,
            "actions_taken": actions,
        }

    async def _basket_update_node(self, state: CartlyState) -> CartlyState:
        """Construct assistant natural language response, persist session, and finalize turn state."""
        session = state["session"]
        basket = state.get("basket", ShoppingBasket())
        pending_clarification = state.get("pending_clarification")
        actions = list(state.get("actions_taken", []))

        if pending_clarification:
            assistant_response = pending_clarification.question
        else:
            if basket.items:
                item_summaries = []
                for item in basket.items:
                    qty_str = (
                        f"{item.quantity:.0f}"
                        if item.quantity.is_integer()
                        else f"{item.quantity}"
                    )
                    item_summaries.append(f"{qty_str}x {item.sku.name}")
                items_str = ", ".join(item_summaries)
                assistant_response = f"Updated your basket: [{items_str}]. Total: ${basket.total_amount:.2f}"
            else:
                assistant_response = "Your shopping basket is currently empty."

        session.basket = basket
        session.pending_clarification = pending_clarification

        assistant_msg = ChatMessage(role="assistant", content=assistant_response)
        session.history.append(assistant_msg)

        max_window = self.session_store.default_window_size
        if len(session.history) > max_window:
            session.history = session.history[-max_window:]

        await self.session_store.save_session(session)
        actions.append("Persisted session state and generated final response")

        return {
            **state,
            "session": session,
            "basket": basket,
            "pending_clarification": pending_clarification,
            "assistant_response": assistant_response,
            "actions_taken": actions,
        }

    def _add_or_update_cart_item(
        self,
        items: List[CartItem],
        sku: SKU,
        quantity: float = 1.0,
        notes: Optional[str] = None,
    ) -> None:
        """Helper to add a new item or increment quantity if SKU already exists in cart."""
        for item in items:
            if item.sku.id == sku.id:
                item.quantity += quantity
                if notes:
                    item.notes = f"{item.notes}; {notes}" if item.notes else notes
                return
        items.append(
            CartItem(sku=sku, quantity=quantity, price_per_unit=sku.price, notes=notes)
        )

    def _find_basket_item_index(
        self,
        items: List[CartItem],
        item_phrase: Optional[str],
        target_sku_id: Optional[str] = None,
    ) -> Optional[int]:
        """Helper to find matching CartItem index in basket by target SKU ID or phrase substring match."""
        if target_sku_id:
            for i, item in enumerate(items):
                if item.sku.id == target_sku_id:
                    return i

        if item_phrase:
            phrase_clean = item_phrase.lower().strip()
            # 1. Exact SKU ID match
            for i, item in enumerate(items):
                if item.sku.id.lower() == phrase_clean:
                    return i
            # 2. Substring match on name or brand
            for i, item in enumerate(items):
                sku_text = f"{item.sku.name} {item.sku.brand or ''}".lower()
                if phrase_clean in sku_text or any(
                    token in sku_text for token in phrase_clean.split()
                ):
                    return i

        return None

    async def process_turn(
        self, session_id: str, user_id: str, message: str
    ) -> ChatResponse:
        """Process a single conversational turn through the LangGraph workflow engine."""
        initial_state: CartlyState = {
            "session_id": session_id,
            "user_id": user_id,
            "user_message": message,
            "actions_taken": [],
        }

        final_state = await self._graph.ainvoke(initial_state)

        return ChatResponse(
            session_id=session_id,
            message=final_state["assistant_response"],
            basket=final_state["basket"],
            pending_clarification=final_state.get("pending_clarification"),
            actions_taken=final_state.get("actions_taken", []),
        )
