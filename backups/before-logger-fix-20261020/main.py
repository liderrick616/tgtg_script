#!/usr/bin/env python3
"""
main.py — CLI entry point for the TGTG Sniper Bot.

Commands:
    login           Authenticate with Too Good To Go via email
    run             Start the polling bot
    list-favorites  Display all favorited items with their IDs
    test-notify     Send a test notification to verify setup
"""

import argparse
import sys
import json

from config_loader import load_config
from logger_setup import setup_logger, get_logger
from auth import get_client, login, has_saved_credentials, load_credentials
from notifier import send_test_notification
from poller import run_polling_loop
from card_store import PaymentSetupError, setup_card, load_card, forget_card
from payment import prepare_payment, validate_settings
from api_client import APIAccessError, check_access


BANNER = r"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   ████████╗ ██████╗ ████████╗ ██████╗                        ║
║   ╚══██╔══╝██╔════╝ ╚══██╔══╝██╔════╝                       ║
║      ██║   ██║  ███╗   ██║   ██║  ███╗                       ║
║      ██║   ██║   ██║   ██║   ██║   ██║                       ║
║      ██║   ╚██████╔╝   ██║   ╚██████╔╝                       ║
║      ╚═╝    ╚═════╝    ╚═╝    ╚═════╝                        ║
║                                                              ║
║   🥡  S N I P E R   B O T                                   ║
║   Auto-reserve Too Good To Go surprise bags                  ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""


def cmd_login(args, config):
    """Run the first-time email authentication flow."""
    log = get_logger()
    print(BANNER)

    email = config.get("tgtg", {}).get("email", "")
    if not email or email == "your_email@example.com":
        log.error("❌ Set your email in config.yaml first!")
        log.info("   Edit config.yaml and set: tgtg.email: \"your@email.com\"")
        sys.exit(1)

    if has_saved_credentials():
        log.warning("⚠️  Saved credentials already exist.")
        log.info("   Running login will overwrite them.")
        confirm = input("   Continue? [y/N]: ").strip().lower()
        if confirm != "y":
            log.info("Aborted.")
            return

    login(email)
    log.info("\n✅ Login complete! You can now run: python main.py run")


def cmd_run(args, config):
    """Start the polling bot."""
    log = get_logger()
    print(BANNER)

    if args.no_burst:
        config["polling"] = {**config["polling"], "burst_windows": []}

    settings = config["payment"]
    if args.auto_pay:
        settings["enabled"] = True
    if args.max_total is not None:
        settings["max_order_total"] = args.max_total
    if args.currency is not None:
        settings["currency"] = args.currency.upper()
    if settings["enabled"]:
        validate_settings(config)

    if not has_saved_credentials():
        log.error("❌ No saved credentials. Run 'python main.py login' first.")
        sys.exit(1)

    client = get_client(config)

    log.info("🚀 Starting TGTG Sniper Bot...")
    log.info("━" * 60)

    # Show configuration summary
    auto_reserve = config.get("reservation", {}).get("auto_reserve", True)
    monitor_all = config.get("monitor_all_favorites", False)
    targets = config.get("targets", [])
    notif = config.get("notifications", {})

    mode = "Auto-Reserve + Pay" if settings["enabled"] else (
        "Auto-Reserve + Notify" if auto_reserve else "Notify Only"
    )
    log.info(f"📋 Mode: {mode}")
    log.info(f"📋 Monitoring: {'All Favorites' if monitor_all else f'{len(targets)} target(s)'}")

    channels = []
    if notif.get("macos_alert"):
        channels.append("macOS")
    if notif.get("telegram", {}).get("enabled"):
        channels.append("Telegram")
    if notif.get("discord", {}).get("enabled"):
        channels.append("Discord")
    log.info(f"📋 Notifications: {', '.join(channels) if channels else 'None ⚠️'}")
    log.info("━" * 60)

    payment = None
    try:
        log.info("Checking API access before payment setup...")
        initial_items = check_access(client)
        log.info("API access verified; received %s favorite item(s).", len(initial_items))
        if settings["enabled"]:
            payment = prepare_payment(client, config)
            log.info("Automatic payment enabled: up to %s %s per order; %s reservation attempt(s) this run.",
                     payment.maximum, payment.currency, payment.max_orders)
        if run_polling_loop(client, config, payment=payment, initial_items=initial_items) is False:
            sys.exit(1)
    finally:
        if payment is not None:
            payment.close()


def cmd_check_access(args, config):
    if not has_saved_credentials():
        raise APIAccessError("No saved login. Run: python3 main.py login")
    items = check_access(get_client(config))
    print(f"API access verified: received {len(items)} favorite item(s). No purchase was attempted.")


def cmd_setup_payment(args, config):
    setup_card(config)


def cmd_payment_status(args, config):
    card = load_card(config)
    print(f"Saved card: ending {card.number[-4:]} (macOS Keychain). CVV is not stored.")
    print(f"Automatic payment in config: {'enabled' if config['payment']['enabled'] else 'disabled'}")
    print("This checks local setup only; a live payment has not been validated.")


def cmd_forget_payment(args, config):
    forget_card(config)
    print("Saved card removed from Keychain. Stop any running bot to clear its in-memory card/CVV.")


def cmd_list_favorites(args, config):
    """List all favorited items with their IDs."""
    log = get_logger()
    print(BANNER)

    if not has_saved_credentials():
        log.error("❌ No saved credentials. Run 'python main.py login' first.")
        sys.exit(1)

    client = get_client(config)

    log.info("📋 Fetching your favorite items...\n")

    try:
        items = client.get_items(favorites_only=True)
    except Exception as e:
        log.error(f"❌ Failed to fetch favorites: {e}")
        sys.exit(1)

    if not items:
        log.info("No favorites found. Add some stores to your favorites in the TGTG app first.")
        return

    print(f"{'─' * 80}")
    print(f"{'Item ID':<12} {'Available':<11} {'Price':<12} {'Store Name'}")
    print(f"{'─' * 80}")

    for item_data in items:
        item = item_data.get("item", {})
        store = item_data.get("store", {})
        item_id = item.get("item_id", "?")
        store_name = store.get("store_name", "Unknown")
        available = item_data.get("items_available", 0)

        # Format price
        price_info = item.get("item_price", {})
        minor_units = price_info.get("minor_units", 0)
        decimals = price_info.get("decimals", 2)
        currency = price_info.get("code", "")
        price_str = f"{minor_units / (10 ** decimals):.{decimals}f} {currency}" if minor_units else "N/A"

        # Availability indicator
        avail_str = f"🟢 {available}" if available > 0 else f"⚪ {available}"

        print(f"{item_id:<12} {avail_str:<11} {price_str:<12} {store_name}")

    print(f"{'─' * 80}")
    print(f"\n📊 Total favorites: {len(items)}")
    print(f"📦 Currently available: {sum(1 for i in items if i.get('items_available', 0) > 0)}")
    print(f"\n💡 Copy the Item ID(s) you want to monitor into config.yaml under 'targets'.")


def cmd_test_notify(args, config):
    """Send a test notification through all enabled channels."""
    log = get_logger()
    print(BANNER)
    log.info("🧪 Sending test notifications...\n")
    send_test_notification(config)
    log.info("\n✅ Test complete! Check your notification channels.")


def main():
    parser = argparse.ArgumentParser(
        description="🥡 TGTG Sniper Bot — Auto-reserve Too Good To Go surprise bags",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py login            First-time authentication
  python main.py run              Start the polling bot
  python main.py list-favorites   Find item IDs for your favorites
  python main.py test-notify      Verify notification setup
        """,
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config.yaml (default: ./config.yaml)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("login", help="Authenticate with Too Good To Go via email")
    run_parser = subparsers.add_parser("run", help="Start the polling bot")
    run_parser.add_argument("--auto-pay", action="store_true", help="Pay automatically after reservation")
    run_parser.add_argument("--max-total", help="Maximum final total per order, including tax")
    run_parser.add_argument("--currency", help="Currency for automatic payment, e.g. CAD")
    run_parser.add_argument("--no-burst", action="store_true", help="Use normal polling interval throughout this run")
    subparsers.add_parser("list-favorites", help="Display all favorited items with IDs")
    subparsers.add_parser("test-notify", help="Send a test notification")
    subparsers.add_parser("setup-payment", help="Save card details in macOS Keychain")
    subparsers.add_parser("payment-status", help="Show local payment setup (does not charge)")
    subparsers.add_parser("forget-payment", help="Remove the saved card from Keychain")
    subparsers.add_parser("check-access", help="Check API access once without reading card details or buying")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # Load configuration
    config = load_config(args.config)

    # Setup logging
    log_config = config.get("logging", {})
    setup_logger(
        level=log_config.get("level", "INFO"),
        log_file=log_config.get("file", "tgtg_bot.log"),
    )

    # Dispatch to command handler
    commands = {
        "login": cmd_login,
        "run": cmd_run,
        "list-favorites": cmd_list_favorites,
        "test-notify": cmd_test_notify,
        "setup-payment": cmd_setup_payment,
        "payment-status": cmd_payment_status,
        "forget-payment": cmd_forget_payment,
        "check-access": cmd_check_access,
    }

    handler = commands.get(args.command)
    if handler:
        try:
            handler(args, config)
        except (PaymentSetupError, APIAccessError) as exc:
            log.error("%s", exc)
            sys.exit(1)
        except KeyboardInterrupt:
            log.info("Stopped.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
