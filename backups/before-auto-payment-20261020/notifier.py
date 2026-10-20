"""
notifier.py — Multi-channel notification system for the TGTG bot.

Supports:
- macOS native notifications (osascript)
- macOS sound alerts
- Telegram Bot API
- Discord webhooks
"""

import json
import subprocess
import requests
from datetime import datetime

from logger_setup import get_logger


def notify_all(config: dict, message: str, title: str = "🥡 TGTG Sniper", details: dict = None):
    """
    Send a notification through all enabled channels.

    Args:
        config: The loaded configuration dictionary.
        message: The notification message body.
        title: The notification title.
        details: Optional dict with extra info (store_name, item_name, price, etc.)
    """
    log = get_logger()
    notif_config = config.get("notifications", {})

    # macOS native notification
    if notif_config.get("macos_alert", True):
        _notify_macos(title, message, play_sound=notif_config.get("play_sound", True))

    # Telegram
    telegram = notif_config.get("telegram", {})
    if telegram.get("enabled"):
        _notify_telegram(telegram, title, message, details)

    # Discord
    discord = notif_config.get("discord", {})
    if discord.get("enabled"):
        _notify_discord(discord, title, message, details)

    log.info(f"📣 Notifications sent: {message[:80]}...")


def notify_stock_detected(config: dict, item_data: dict, reserved: bool = False, order_id: str = None):
    """
    Send a formatted notification when stock is detected.

    Args:
        config: Configuration dictionary.
        item_data: The item data dict from the TGTG API.
        reserved: Whether the bag was auto-reserved.
        order_id: The order ID if reserved.
    """
    store_name = item_data.get("store", {}).get("store_name", "Unknown Store")
    item_name = item_data.get("item", {}).get("name", "Surprise Bag")
    item_id = item_data.get("item", {}).get("item_id", "?")
    available = item_data.get("items_available", 0)

    # Format price
    price_info = item_data.get("item", {}).get("item_price", {})
    minor_units = price_info.get("minor_units", 0)
    decimals = price_info.get("decimals", 2)
    currency = price_info.get("code", "")
    price_str = f"{minor_units / (10 ** decimals):.{decimals}f} {currency}" if minor_units else "N/A"

    if reserved:
        title = "🎉 BAG RESERVED!"
        status_line = f"✅ Reserved! Order ID: {order_id}"
        action_line = "⏰ Open the TGTG app NOW and tap PAY within 5 minutes!"
    else:
        title = "🔔 BAG AVAILABLE!"
        status_line = "⚡ Stock detected — grab it in the app!"
        action_line = "📱 Open the TGTG app and order NOW!"

    message = (
        f"🏪 {store_name}\n"
        f"🥡 {item_name or 'Surprise Bag'}\n"
        f"💰 {price_str}\n"
        f"📦 Available: {available}\n"
        f"🆔 Item ID: {item_id}\n"
        f"\n{status_line}\n"
        f"{action_line}"
    )

    details = {
        "store_name": store_name,
        "item_name": item_name or "Surprise Bag",
        "price": price_str,
        "available": available,
        "item_id": item_id,
        "reserved": reserved,
        "order_id": order_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    notify_all(config, message, title=title, details=details)


def _notify_macos(title: str, message: str, play_sound: bool = True):
    """Send a macOS native notification via osascript."""
    log = get_logger()
    try:
        # Escape quotes for AppleScript
        escaped_message = message.replace('"', '\\"').replace("'", "'")
        escaped_title = title.replace('"', '\\"')

        script = f'display notification "{escaped_message}" with title "{escaped_title}"'
        if play_sound:
            script += ' sound name "Glass"'

        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=5,
        )

        # Also play a louder alert sound to really grab attention
        if play_sound:
            subprocess.run(
                ["afplay", "/System/Library/Sounds/Hero.aiff"],
                capture_output=True,
                timeout=5,
            )

        log.debug("macOS notification sent.")
    except Exception as e:
        log.warning(f"macOS notification failed: {e}")


def _notify_telegram(telegram_config: dict, title: str, message: str, details: dict = None):
    """Send a Telegram message via Bot API."""
    log = get_logger()
    bot_token = telegram_config.get("bot_token", "")
    chat_id = telegram_config.get("chat_id", "")

    if not bot_token or not chat_id:
        log.warning("Telegram bot_token or chat_id not configured.")
        return

    # Format a rich Telegram message
    text = f"*{title}*\n\n{message}"

    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            log.debug("Telegram notification sent.")
        else:
            log.warning(f"Telegram API error: {resp.status_code} — {resp.text}")
    except Exception as e:
        log.warning(f"Telegram notification failed: {e}")


def _notify_discord(discord_config: dict, title: str, message: str, details: dict = None):
    """Send a Discord notification via webhook."""
    log = get_logger()
    webhook_url = discord_config.get("webhook_url", "")

    if not webhook_url:
        log.warning("Discord webhook_url not configured.")
        return

    # Build a rich embed
    embed = {
        "title": title,
        "description": message,
        "color": 0x00C853 if details and details.get("reserved") else 0xFF6D00,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "TGTG Sniper Bot"},
    }

    if details:
        embed["fields"] = [
            {"name": "Store", "value": details.get("store_name", "?"), "inline": True},
            {"name": "Price", "value": details.get("price", "?"), "inline": True},
            {"name": "Available", "value": str(details.get("available", "?")), "inline": True},
        ]

    try:
        payload = {"embeds": [embed]}
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            log.debug("Discord notification sent.")
        else:
            log.warning(f"Discord webhook error: {resp.status_code} — {resp.text}")
    except Exception as e:
        log.warning(f"Discord notification failed: {e}")


def send_test_notification(config: dict):
    """Send a test notification through all enabled channels."""
    notify_all(
        config,
        message=(
            "🏪 Test Bakery\n"
            "🥡 Surprise Bag\n"
            "💰 5.99 CAD\n"
            "📦 Available: 3\n"
            "\n✅ This is a test notification!\n"
            "📱 If you see this, your notifications are working."
        ),
        title="🧪 TGTG Bot — Test Notification",
        details={
            "store_name": "Test Bakery",
            "item_name": "Surprise Bag",
            "price": "5.99 CAD",
            "available": 3,
            "item_id": "000000",
            "reserved": False,
            "order_id": None,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )
