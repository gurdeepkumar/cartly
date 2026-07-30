from typing import Any, Dict, List, Optional
import json
import logging
import re
from litellm import acompletion, completion
from pydantic import ValidationError

from src.cartly.config import settings
from src.cartly.models.schemas import (
    ChatMessage,
    IntentActionEnum,
    ParsedIntent,
    ShoppingBasket,
)

logger = logging.getLogger(__name__)


class IntentParserError(Exception):
    """Base exception for intent extraction errors."""

    pass


INTENT_SYSTEM_PROMPT = """You are an expert intent parsing system for Cartly, a shopping assistant application.
Your task is to analyze the user's latest input within the conversation context and current basket state, and extract the user's intent into a structured JSON object.

Valid intent actions (IntentActionEnum):
- ADD: User wants to add item(s) to the shopping basket.
- REMOVE: User wants to remove item(s) from the basket.
- MODIFY_QUANTITY: User wants to change the quantity of an existing item in the basket.
- SUBSTITUTE: User wants to substitute or replace an item with another.
- CLARIFY: User query is ambiguous, incomplete, or requires clarification before taking action.

Output MUST be a JSON object matching this schema strictly:
{
  "action": "<ADD | REMOVE | MODIFY_QUANTITY | SUBSTITUTE | CLARIFY>",
  "query": "<raw query phrase or main product request, e.g. '2 gallons of whole milk'>",
  "extracted_items": ["<product name 1>", "<product name 2>"],
  "target_sku_id": "<target SKU ID if explicitly mentioned or resolved, else null>",
  "quantity": <float quantity specified, e.g. 1.0, 2.0, default 1.0>,
  "clarify_reason": "<explanation if action is CLARIFY, else null>",
  "confidence": <float confidence score between 0.0 and 1.0>
}

Sampling Guidance:
- Set temperature to 0.0 for deterministic output.
"""


class LiteLLMIntentParser:
    """Model-agnostic intent parser powered by LiteLLM with structured output parsing and fallback handling."""

    def __init__(
        self,
        model: Optional[str] = None,
        fallback_models: Optional[List[str]] = None,
        api_key: Optional[str] = None,
        temperature: float = 0.0,
    ):
        self.model = model or settings.LLM_MODEL
        self.fallback_models = (
            fallback_models if fallback_models is not None else ["gpt-3.5-turbo"]
        )
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.temperature = temperature

    def _build_prompt_messages(
        self,
        user_message: str,
        history: Optional[List[ChatMessage]] = None,
        current_basket: Optional[ShoppingBasket] = None,
    ) -> List[Dict[str, str]]:
        messages = [{"role": "system", "content": INTENT_SYSTEM_PROMPT}]

        # Context summary
        context_parts = []
        if current_basket and current_basket.items:
            basket_summary = ", ".join(
                [
                    f"{item.sku.name} (qty: {item.quantity})"
                    for item in current_basket.items
                ]
            )
            context_parts.append(f"Current Basket: [{basket_summary}]")
        else:
            context_parts.append("Current Basket: [Empty]")

        if history:
            recent_turns = history[-5:]  # last 5 turns for context
            formatted_history = "\n".join(
                [f"{msg.role.upper()}: {msg.content}" for msg in recent_turns]
            )
            context_parts.append(f"Recent History:\n{formatted_history}")

        if context_parts:
            context_str = "\n".join(context_parts)
            messages.append(
                {"role": "system", "content": f"Session Context:\n{context_str}"}
            )

        messages.append({"role": "user", "content": user_message})
        return messages

    def _parse_response_content(self, raw_content: str) -> ParsedIntent:
        """Parse raw JSON string output from LLM into ParsedIntent."""
        content = raw_content.strip()

        # Handle potential markdown code blocks in response
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        data = json.loads(content)
        return ParsedIntent.model_validate(data)

    def _fallback_heuristic_parse(self, user_message: str) -> ParsedIntent:
        """Heuristic rule-based fallback parser when LLM calls fail."""
        text = user_message.strip().lower()

        # Check remove
        remove_match = re.search(
            r"\b(remove|delete|drop|take out)\s+(?:(\d+(?:\.\d+)?)\s+)?(.+)", text
        )
        if remove_match:
            qty = float(remove_match.group(2)) if remove_match.group(2) else 1.0
            item = remove_match.group(3).strip()
            return ParsedIntent(
                action=IntentActionEnum.REMOVE,
                query=user_message,
                extracted_items=[item],
                quantity=qty,
                confidence=0.6,
            )

        # Check modify quantity
        modify_match = re.search(
            r"\b(change|set|modify|update)\s+(?:quantity of\s+)?(.+?)\s+to\s+(\d+(?:\.\d+)?)",
            text,
        )
        if modify_match:
            item = modify_match.group(2).strip()
            qty = float(modify_match.group(3))
            return ParsedIntent(
                action=IntentActionEnum.MODIFY_QUANTITY,
                query=user_message,
                extracted_items=[item],
                quantity=qty,
                confidence=0.6,
            )

        # Check substitute
        sub_match = re.search(
            r"\b(substitute|replace|swap)\s+(.+?)\s+with\s+(.+)", text
        )
        if sub_match:
            orig_item = sub_match.group(2).strip()
            new_item = sub_match.group(3).strip()
            return ParsedIntent(
                action=IntentActionEnum.SUBSTITUTE,
                query=user_message,
                extracted_items=[orig_item, new_item],
                quantity=1.0,
                confidence=0.6,
            )

        # Check add
        add_match = re.search(
            r"\b(add|buy|get|need|want|put|include)\s+(?:(\d+(?:\.\d+)?)\s+)?(.+)", text
        )
        if add_match:
            qty = float(add_match.group(2)) if add_match.group(2) else 1.0
            item = add_match.group(3).strip()
            return ParsedIntent(
                action=IntentActionEnum.ADD,
                query=user_message,
                extracted_items=[item],
                quantity=qty,
                confidence=0.6,
            )

        # Default fallback: Clarification
        return ParsedIntent(
            action=IntentActionEnum.CLARIFY,
            query=user_message,
            extracted_items=[],
            quantity=1.0,
            clarify_reason="Could not determine specific shopping intent from input.",
            confidence=0.3,
        )

    async def aparse_intent(
        self,
        user_message: str,
        history: Optional[List[ChatMessage]] = None,
        current_basket: Optional[ShoppingBasket] = None,
    ) -> ParsedIntent:
        """Async parse intent using LiteLLM with automatic fallback chain."""
        messages = self._build_prompt_messages(user_message, history, current_basket)
        models_to_try = [self.model] + self.fallback_models

        for model in models_to_try:
            try:
                kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                }
                if self.api_key:
                    kwargs["api_key"] = self.api_key

                response = await acompletion(**kwargs)
                raw_text = response.choices[0].message.content
                if raw_text:
                    parsed = self._parse_response_content(raw_text)
                    logger.info(f"Successfully parsed intent using model '{model}'")
                    return parsed
            except Exception as e:
                logger.warning(
                    f"Intent parsing failed with model '{model}': {e}. Trying fallback models..."
                )

        logger.warning(
            "All LLM attempts failed for intent parsing. Using heuristic fallback parser."
        )
        return self._fallback_heuristic_parse(user_message)

    def parse_intent(
        self,
        user_message: str,
        history: Optional[List[ChatMessage]] = None,
        current_basket: Optional[ShoppingBasket] = None,
    ) -> ParsedIntent:
        """Synchronous parse intent using LiteLLM with automatic fallback chain."""
        messages = self._build_prompt_messages(user_message, history, current_basket)
        models_to_try = [self.model] + self.fallback_models

        for model in models_to_try:
            try:
                kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                }
                if self.api_key:
                    kwargs["api_key"] = self.api_key

                response = completion(**kwargs)
                raw_text = response.choices[0].message.content
                if raw_text:
                    parsed = self._parse_response_content(raw_text)
                    logger.info(f"Successfully parsed intent using model '{model}'")
                    return parsed
            except Exception as e:
                logger.warning(
                    f"Intent parsing failed with model '{model}': {e}. Trying fallback models..."
                )

        logger.warning(
            "All LLM attempts failed for intent parsing. Using heuristic fallback parser."
        )
        return self._fallback_heuristic_parse(user_message)
