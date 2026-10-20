"""
poller.py — Smart polling engine with adaptive rate limiting for the TGTG bot.

Features:
- Normal mode: polls at a relaxed interval (60-120s)
- Burst mode: polls aggressively during user-defined drop windows (2-5s)
- Jitter: randomizes intervals to mimic human behavior
- DataDome-aware: backs off on 403 errors
- Periodic credential refresh
"""

import random
import time
import signal
import sys
from datetime import datetime, timedelta

from tgtg import TgtgClient

from logger_setup import get_logger
from auth import refresh_and_save
from reserver import attempt_reserve


# Track which items we've already reserved in this session to avoid duplicates
_reserved_this_session = set()

# Graceful shutdown flag
_shutdown_requested = False


def _signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    global _shutdown_requested
    _shutdown_requested = True
    log = get_logger()
    log.info("\n🛑 Shutdown requested. Finishing current cycle...")


def _is_in_burst_window(burst_windows: list) -> bool:
    """
    Check if the current time falls within any configured burst window.

    Args:
        burst_windows: List of dicts with 'start' and 'end' keys (HH:MM format).

    Returns:
        True if currently in a burst window.
    """
    now = datetime.now()
    current_time = now.strftime("%H:%M")

    for window in burst_windows:
        start = window.get("start", "")
        end = window.get("end", "")
        if start and end:
            if start <= current_time <= end:
                return True
    return False


def _get_poll_interval(config: dict) -> float:
    """
    Calculate the next polling interval based on current time and config.

    Args:
        config: Configuration dictionary.

    Returns:
        Sleep duration in seconds (with jitter applied).
    """
    polling = config.get("polling", {})
    burst_windows = polling.get("burst_windows", [])
    jitter_min = polling.get("jitter_min", 0.5)
    jitter_max = polling.get("jitter_max", 1.8)

    if _is_in_burst_window(burst_windows):
        base = polling.get("burst_interval", 3)
    else:
        base = polling.get("normal_interval", 90)

    jitter = random.uniform(jitter_min, jitter_max)
    return base + jitter


def _get_target_item_ids(config: dict) -> set:
    """
    Get the set of item IDs to monitor.

    Args:
        config: Configuration dictionary.

    Returns:
        Set of item ID strings.
    """
    targets = config.get("targets", [])
    return {str(t.get("item_id", "")) for t in targets if t.get("item_id")}


def _get_target_names(config: dict) -> dict:
    """Get a mapping of item_id -> friendly name from config."""
    targets = config.get("targets", [])
    return {str(t.get("item_id", "")): t.get("name", "") for t in targets if t.get("item_id")}


def run_polling_loop(client: TgtgClient, config: dict):
    """
    Main polling loop. Monitors target items and triggers reservations.

    This function runs indefinitely until interrupted with Ctrl+C.

    Args:
        client: Authenticated TgtgClient instance.
        config: Configuration dictionary.
    """
    global _shutdown_requested, _reserved_this_session

    log = get_logger()
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    monitor_all = config.get("monitor_all_favorites", False)
    target_ids = _get_target_item_ids(config)
    target_names = _get_target_names(config)
    polling_config = config.get("polling", {})
    error_cooldown = polling_config.get("error_cooldown", 300)

    if monitor_all:
        log.info("📡 Monitoring ALL favorites...")
    elif target_ids:
        names_display = ", ".join(
            f"{tid} ({target_names.get(tid, 'unnamed')})" for tid in target_ids
        )
        log.info(f"🎯 Monitoring targets: {names_display}")
    else:
        log.error("❌ No items to monitor. Configure targets in config.yaml or set monitor_all_favorites: true.")
        return

    # Show burst windows
    burst_windows = polling_config.get("burst_windows", [])
    if burst_windows:
        windows_str = ", ".join(f"{w['start']}-{w['end']}" for w in burst_windows)
        log.info(f"⚡ Burst windows configured: {windows_str}")
    else:
        log.info("ℹ️  No burst windows configured. Using normal polling rate only.")

    log.info(f"🔄 Normal interval: {polling_config.get('normal_interval', 90)}s | "
             f"Burst interval: {polling_config.get('burst_interval', 3)}s")
    log.info("━" * 60)
    log.info("🚀 Polling started. Press Ctrl+C to stop.\n")

    poll_count = 0
    last_credential_refresh = datetime.now()
    consecutive_errors = 0

    while not _shutdown_requested:
        poll_count += 1
        is_burst = _is_in_burst_window(burst_windows)
        mode_label = "⚡BURST" if is_burst else "🔄NORMAL"

        try:
            # Fetch items
            if monitor_all:
                items = client.get_items(favorites_only=True)
            else:
                items = client.get_items(favorites_only=True)

            consecutive_errors = 0  # Reset on success

            # Filter to target items
            available_items = []
            for item_data in items:
                item_id = str(item_data.get("item", {}).get("item_id", ""))
                items_available = item_data.get("items_available", 0)
                store_name = item_data.get("store", {}).get("store_name", "?")

                # Check if this is a target item (or we're monitoring all favorites)
                is_target = monitor_all or item_id in target_ids

                if is_target and items_available > 0:
                    available_items.append(item_data)
                    log.info(f"🟢 {store_name} (ID: {item_id}): {items_available} bags available!")
                elif is_target:
                    friendly = target_names.get(item_id, store_name)
                    log.debug(f"⚪ {friendly} (ID: {item_id}): no stock")

            # Process available items
            for item_data in available_items:
                item_id = str(item_data.get("item", {}).get("item_id", ""))
                if item_id not in _reserved_this_session:
                    order = attempt_reserve(client, config, item_data)
                    if order:
                        _reserved_this_session.add(item_id)
                        log.info(f"💾 Item {item_id} marked as reserved this session.")
                else:
                    log.debug(f"⏭️  Item {item_id} already reserved this session. Skipping.")

            # Status line
            now = datetime.now().strftime("%H:%M:%S")
            log.info(f"[{now}] Poll #{poll_count} | {mode_label} | "
                     f"Checked: {len(items)} items | Available: {len(available_items)}")

        except KeyboardInterrupt:
            break

        except Exception as e:
            consecutive_errors += 1
            error_msg = str(e)

            if "403" in error_msg or "Forbidden" in error_msg:
                log.error(f"🚫 DataDome block detected! Cooling down for {error_cooldown}s...")
                log.warning("   Consider using a residential IP or reducing polling frequency.")
                _sleep_with_interrupt(error_cooldown)
                continue
            elif "429" in error_msg:
                backoff = min(60 * consecutive_errors, 300)
                log.warning(f"⏳ Rate limited (429). Backing off for {backoff}s...")
                _sleep_with_interrupt(backoff)
                continue
            else:
                backoff = min(10 * consecutive_errors, 120)
                log.error(f"❌ Poll error (attempt {consecutive_errors}): {error_msg}")
                log.info(f"   Retrying in {backoff}s...")
                _sleep_with_interrupt(backoff)
                continue

        # Periodic credential refresh (every 30 minutes)
        if datetime.now() - last_credential_refresh > timedelta(minutes=30):
            log.debug("🔄 Refreshing credentials...")
            refresh_and_save(client)
            last_credential_refresh = datetime.now()

        # Sleep until next poll
        interval = _get_poll_interval(config)
        log.debug(f"💤 Sleeping {interval:.1f}s until next poll...")
        _sleep_with_interrupt(interval)

    log.info("\n🛑 Polling stopped.")
    log.info(f"   Total polls: {poll_count}")
    log.info(f"   Items reserved this session: {len(_reserved_this_session)}")


def _sleep_with_interrupt(seconds: float):
    """Sleep for the given duration, but wake up immediately on shutdown signal."""
    global _shutdown_requested
    end_time = time.time() + seconds
    while time.time() < end_time and not _shutdown_requested:
        time.sleep(min(0.5, end_time - time.time()))
