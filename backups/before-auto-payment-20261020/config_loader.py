"""
config_loader.py — YAML configuration parser and validator for the TGTG bot.
"""

import os
import sys
import yaml


# Default configuration values
DEFAULTS = {
    "tgtg": {"email": ""},
    "monitor_all_favorites": False,
    "targets": [],
    "polling": {
        "normal_interval": 90,
        "burst_interval": 3,
        "jitter_min": 0.5,
        "jitter_max": 1.8,
        "burst_windows": [],
        "error_cooldown": 300,
    },
    "reservation": {
        "auto_reserve": True,
        "quantity": 1,
    },
    "notifications": {
        "macos_alert": True,
        "play_sound": True,
        "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
        "discord": {"enabled": False, "webhook_url": ""},
    },
    "logging": {
        "level": "INFO",
        "file": "tgtg_bot.log",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, preferring override values."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: str = None) -> dict:
    """
    Load and validate the config.yaml file.

    Args:
        config_path: Path to config.yaml. Defaults to config.yaml in the script directory.

    Returns:
        Merged configuration dictionary with defaults applied.
    """
    if config_path is None:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

    if not os.path.exists(config_path):
        print(f"❌ Config file not found: {config_path}")
        print("   Run the bot from the project directory or specify --config path.")
        sys.exit(1)

    with open(config_path, "r") as f:
        raw = yaml.safe_load(f) or {}

    config = _deep_merge(DEFAULTS, raw)
    _validate(config)
    return config


def _validate(config: dict):
    """Validate critical configuration values."""
    # Check email is set
    email = config.get("tgtg", {}).get("email", "")
    if not email or email == "your_email@example.com":
        print("⚠️  Warning: TGTG email not configured in config.yaml.")
        print("   You'll need to set it before running 'login'.")

    # Validate polling intervals
    polling = config.get("polling", {})
    if polling.get("normal_interval", 90) < 10:
        print("⚠️  Warning: normal_interval < 10s is very aggressive and risks a ban.")
    if polling.get("burst_interval", 3) < 1:
        print("⚠️  Warning: burst_interval < 1s is extremely aggressive. Recommended: 2-5s.")

    # Validate targets
    targets = config.get("targets", [])
    monitor_all = config.get("monitor_all_favorites", False)
    if not targets and not monitor_all:
        print("⚠️  Warning: No target items configured and monitor_all_favorites is false.")
        print("   The bot won't monitor anything. Add item IDs to config.yaml or set monitor_all_favorites: true.")

    # Validate burst windows
    for window in polling.get("burst_windows", []):
        if "start" not in window or "end" not in window:
            print(f"⚠️  Warning: Burst window missing 'start' or 'end': {window}")

    # Validate notification channels
    notif = config.get("notifications", {})
    telegram = notif.get("telegram", {})
    discord = notif.get("discord", {})
    macos = notif.get("macos_alert", False)

    if not macos and not telegram.get("enabled") and not discord.get("enabled"):
        print("⚠️  Warning: No notification channels enabled. You won't be alerted when bags drop!")

    if telegram.get("enabled"):
        if not telegram.get("bot_token") or not telegram.get("chat_id"):
            print("❌ Telegram is enabled but bot_token or chat_id is missing.")

    if discord.get("enabled"):
        if not discord.get("webhook_url"):
            print("❌ Discord is enabled but webhook_url is missing.")
