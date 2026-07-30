import pytest
from src.cartly.services.crm import PastOrder, PastOrderItem


def test_past_order_item_validation_handles_string():
    # This simulates the error report: "input_value='prod_001', input_type=str"
    # The fix should now allow this and convert it to a PastOrderItem object.

    data = {"order_id": "order_123", "items": ["prod_001"], "total_amount": 10.0}

    order = PastOrder.model_validate(data)

    assert len(order.items) == 1
    assert isinstance(order.items[0], PastOrderItem)
    assert order.items[0].sku_id == "prod_001"
    assert order.items[0].name == "Unknown Product"


def test_past_order_item_validation_success_with_dict():
    data = {
        "order_id": "order_123",
        "items": [
            {
                "sku_id": "prod_001",
                "name": "Product 1",
                "quantity": 1.0,
                "unit_price": 10.0,
            }
        ],
        "total_amount": 10.0,
    }
    order = PastOrder.model_validate(data)
    assert order.items[0].sku_id == "prod_001"
    assert order.items[0].name == "Product 1"


def test_past_order_handles_missing_total_amount():
    # This simulates the new error report where total_amount is missing
    data = {"order_id": "order-001", "items": ["prod_001", "prod_004"]}

    order = PastOrder.model_validate(data)
    assert order.order_id == "order-001"
    assert order.total_amount == 0.0
    assert len(order.items) == 2
    assert order.items[1].sku_id == "prod_004"
