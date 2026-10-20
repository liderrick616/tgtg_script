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

    log.info(f"📋 Mode: {'Auto-Reserve + Notify' if auto_reserve else 'Notify Only'}")
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

    run_polling_loop(client, config)


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
    subparsers.add_parser("run", help="Start the polling bot")
    subparsers.add_parser("list-favorites", help="Display all favorited items with IDs")
    subparsers.add_parser("test-notify", help="Send a test notification")

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
    }

    handler = commands.get(args.command)
    if handler:
        handler(args, config)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
