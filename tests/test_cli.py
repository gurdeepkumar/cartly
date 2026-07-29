from unittest.mock import AsyncMock, patch
import pytest

from src.cartly.cli import format_basket, print_banner, print_help, cli_loop
from src.cartly.models.schemas import CartItem, SKU, ShoppingBasket


def test_format_basket_empty():
    basket = ShoppingBasket(items=[])
    result = format_basket(basket)
    assert "empty" in result


def test_format_basket_with_items():
    sku = SKU(id="sku-1", name="Whole Milk", price=3.49)
    cart_item = CartItem(sku=sku, quantity=2.0, price_per_unit=3.49)
    basket = ShoppingBasket(items=[cart_item], currency="USD")
    result = format_basket(basket)
    assert "Whole Milk x 2 @ $3.49" in result
    assert "Total Amount: $6.98 USD" in result


def test_print_banner(capsys):
    print_banner("session-123", "user-456")
    captured = capsys.readouterr()
    assert "session-123" in captured.out
    assert "user-456" in captured.out


def test_print_help(capsys):
    print_help()
    captured = capsys.readouterr()
    assert "Cartly CLI Help" in captured.out
    assert "cart / basket" in captured.out


@pytest.mark.asyncio
async def test_cli_loop_exit_command():
    inputs = ["exit"]
    with patch("builtins.input", side_effect=inputs):
        with patch("builtins.print") as mock_print:
            await cli_loop(session_id="test-session", user_id="test-user")
            mock_print.assert_any_call("Exiting Cartly interactive session. Goodbye!")


@pytest.mark.asyncio
async def test_cli_loop_help_and_cart_and_clear():
    inputs = ["help", "cart", "clear", "quit"]
    with patch("builtins.input", side_effect=inputs):
        await cli_loop(session_id="test-session-2", user_id="test-user-2")


@pytest.mark.asyncio
async def test_cli_loop_empty_checkout(capsys):
    inputs = ["checkout", "exit"]
    with patch("builtins.input", side_effect=inputs):
        await cli_loop(session_id="test-session-3", user_id="test-user-3")
        captured = capsys.readouterr()
        assert "shopping basket is empty" in captured.out
