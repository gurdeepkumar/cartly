from src.cartly.services import (
    INTENT_SYSTEM_PROMPT,
    BaseSessionStore,
    CatalogError,
    IntentParserError,
    LiteLLMIntentParser,
    MockCatalogAdapter,
    MockCRMAdapter,
)


def test_services_package_exports():
    """Verify all key service interfaces are exposed via package root."""
    assert BaseSessionStore is not None
    assert MockCatalogAdapter is not None
    assert MockCRMAdapter is not None
    assert CatalogError is not None
    assert LiteLLMIntentParser is not None
    assert IntentParserError is not None
    assert isinstance(INTENT_SYSTEM_PROMPT, str)
