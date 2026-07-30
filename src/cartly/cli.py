import argparse
import asyncio
import sys
from typing import Optional

from src.cartly.models.schemas import ChatSession, CheckoutHandshakeRequest
from src.cartly.services.checkout import CheckoutService, EmptyBasketError
from src.cartly.services.session import SessionNotFoundError
from src.cartly.services.workflow import CartlyWorkflowEngine


def print_banner(session_id: str, user_id: str) -> None:
    print("=" * 60)
    print("       🛒  Welcome to Cartly Conversational Shopping  🛒       ")
    print("=" * 60)
    print(f" Session ID : {session_id}")
    print(f" User ID    : {user_id}")
    print("-" * 60)
    print(" Special Commands:")
    print("   'cart' or 'basket' - View current active shopping basket")
    print("   'checkout'        - Convert basket to supermarket order payload")
    print("   'clear' or 'reset'- Reset current session & basket")
    print("   'help'            - Display available commands & examples")
    print("   'exit' or 'quit'  - Exit interactive runner")
    print("=" * 60)
    print()


def print_help() -> None:
    print("\n--- Cartly CLI Help ---")
    print("Commands:")
    print("  cart / basket    - Show current shopping basket contents and total price.")
    print("  checkout         - Process final supermarket checkout handshake.")
    print("  clear / reset    - Clear session history and empty the basket.")
    print("  exit / quit      - Exit the CLI terminal application.")
    print("\nExample User Messages:")
    print("  - 'Add 2 bottles of milk'")
    print("  - 'I want to cook spaghetti carbonara'")
    print("  - 'Remove the bread'")
    print("  - 'Substitute milk with oat milk'")
    print("  - 'Change quantity of eggs to 2'")
    print("-------------------------\n")


def format_basket(basket) -> str:
    if not basket or not basket.items:
        return "🛒 Your shopping basket is currently empty."

    lines = [f"\n🛒 Shopping Basket ({len(basket.items)} items):"]
    lines.append("-" * 50)
    for idx, item in enumerate(basket.items, 1):
        qty_str = (
            f"{item.quantity:.0f}"
            if item.quantity.is_integer()
            else f"{item.quantity:.2f}"
        )
        note_str = f" ({item.notes})" if item.notes else ""
        lines.append(
            f"  {idx}. {item.sku.name} x {qty_str} @ ${item.price_per_unit:.2f} = ${item.total_price:.2f}{note_str}"
        )
    lines.append("-" * 50)
    lines.append(f" Total Amount: ${basket.total_amount:.2f} {basket.currency}")
    lines.append("")
    return "\n".join(lines)


async def cli_loop(
    session_id: str = "cli-session-1", user_id: str = "user_123", verbose: bool = False
):
    engine = CartlyWorkflowEngine()
    checkout_service = CheckoutService(session_store=engine.session_store)

    print_banner(session_id, user_id)

    try:
        while True:
            try:
                user_input = input(f"Cartly [{user_id}] > ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\nExiting Cartly interactive session. Goodbye!")
                break

            if not user_input:
                continue

            cmd = user_input.lower()
            if cmd in ("exit", "quit"):
                print("Exiting Cartly interactive session. Goodbye!")
                break
            elif cmd == "help":
                print_help()
                continue
            elif cmd in ("cart", "basket"):
                session = await engine.session_store.get_session(session_id)
                basket = (
                    session.basket
                    if session
                    else (await engine.process_turn(session_id, user_id, "")).basket
                )
                print(format_basket(basket))
                continue
            elif cmd in ("clear", "reset"):
                await engine.session_store.delete_session(session_id)
                print("🧹 Session history and basket reset successfully.\n")
                continue
            elif cmd == "checkout":
                try:
                    session = await engine.session_store.get_session(session_id)
                    if not session:
                        session = ChatSession(session_id=session_id, user_id=user_id)
                    request = CheckoutHandshakeRequest(
                        session_id=session_id, user_id=user_id
                    )
                    result = await checkout_service.process_handshake(
                        request, session=session
                    )
                    print("\n✅ Checkout Handshake Successful!")
                    print(f" Confirmation Code : {result.confirmation_code}")
                    print(
                        f" Order Total       : ${result.checkout_payload.total_amount:.2f} {result.checkout_payload.currency}"
                    )
                    print(f" Total Line Items  : {result.checkout_payload.total_items}")
                    print(f" Message           : {result.message}\n")
                except (EmptyBasketError, SessionNotFoundError):
                    print("\n⚠️ Cannot checkout: Your shopping basket is empty.\n")
                except Exception as exc:
                    print(f"\n❌ Checkout failed: {exc}\n")
                continue

            # Process conversational turn
            response = await engine.process_turn(session_id, user_id, user_input)

            print(f"\nAssistant: {response.message}")
            if response.pending_clarification:
                print(
                    f"❓ Pending Clarification: {response.pending_clarification.question}"
                )

            if verbose and response.actions_taken:
                print("⚙️  Actions Taken:")
                for action in response.actions_taken:
                    print(f"   - {action}")

            print(format_basket(response.basket))

    finally:
        await checkout_service.close()


def main():
    parser = argparse.ArgumentParser(description="Cartly Interactive Terminal Chat CLI")
    parser.add_argument(
        "--session-id", default="cli-session-1", help="Session ID for the conversation"
    )
    parser.add_argument("--user-id", default="user-123", help="User ID for CRM context")
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Display internal workflow actions taken",
    )
    args = parser.parse_args()

    asyncio.run(
        cli_loop(session_id=args.session_id, user_id=args.user_id, verbose=args.verbose)
    )


if __name__ == "__main__":
    main()
