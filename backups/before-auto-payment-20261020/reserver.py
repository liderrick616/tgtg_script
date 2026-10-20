"""
reserver.py — Order reservation engine for the TGTG bot.

Handles creating reservations and monitoring order status.
"""

from tgtg import TgtgClient

from logger_setup import get_logger
from notifier import notify_stock_detected


def attempt_reserve(client: TgtgClient, config: dict, item_data: dict) -> dict | None:
    """
    Attempt to reserve a surprise bag.

    If auto_reserve is enabled in config, calls create_order to lock the bag
    in the user's account for ~5 minutes. Then sends notifications.

    If auto_reserve is disabled, just sends a notification about availability.

    Args:
        client: Authenticated TgtgClient instance.
        config: Configuration dictionary.
        item_data: The item data dict from the TGTG API response.

    Returns:
        Order response dict if reservation succeeded, None otherwise.
    """
    log = get_logger()
    reservation_config = config.get("reservation", {})
    auto_reserve = reservation_config.get("auto_reserve", True)
    quantity = reservation_config.get("quantity", 1)

    item_id = item_data.get("item", {}).get("item_id", "?")
    store_name = item_data.get("store", {}).get("store_name", "Unknown")
    available = item_data.get("items_available", 0)

    if not auto_reserve:
        # Notify-only mode
        log.info(f"🔔 Stock detected at {store_name} (ID: {item_id}) — {available} available")
        log.info("ℹ️  Auto-reserve disabled. Sending notification only.")
        notify_stock_detected(config, item_data, reserved=False)
        return None

    # Auto-reserve mode — try to lock the bag
    log.info(f"🎯 STOCK DETECTED at {store_name}! Attempting reservation...")
    log.info(f"   Item ID: {item_id} | Available: {available} | Reserving: {quantity}")

    try:
        order = client.create_order(item_id=item_id, item_count=quantity)
        order_id = order.get("id", order.get("order_id", "unknown"))

        log.info(f"🎉 RESERVED! Order ID: {order_id}")
        log.info(f"⏰ You have ~5 minutes to pay in the TGTG app!")

        # Send urgent notifications
        notify_stock_detected(config, item_data, reserved=True, order_id=str(order_id))

        return order

    except Exception as e:
        error_msg = str(e)
        log.error(f"❌ Reservation failed for {store_name} (ID: {item_id}): {error_msg}")

        if "ITEMS_NOT_AVAILABLE" in error_msg or "sold out" in error_msg.lower():
            log.warning("   Bag sold out before we could reserve it. Better luck next time!")
        elif "403" in error_msg:
            log.warning("   Possible DataDome block. Consider increasing polling interval.")
        elif "ORDER_LIMIT" in error_msg:
            log.warning("   Order limit reached for this item. You may already have an active order.")
        else:
            log.warning(f"   Unexpected error: {error_msg}")

        # Still notify about availability even if reservation failed
        notify_stock_detected(config, item_data, reserved=False)
        return None


def check_order_status(client: TgtgClient, order_id: str) -> dict | None:
    """
    Check the status of an existing order.

    Args:
        client: Authenticated TgtgClient instance.
        order_id: The order ID to check.

    Returns:
        Order status dict, or None on error.
    """
    log = get_logger()
    try:
        status = client.get_order_status(order_id=order_id)
        log.debug(f"Order {order_id} status: {status}")
        return status
    except Exception as e:
        log.warning(f"Could not check order status for {order_id}: {e}")
        return None


def abort_order(client: TgtgClient, order_id: str) -> bool:
    """
    Abort/cancel an active reservation.

    Args:
        client: Authenticated TgtgClient instance.
        order_id: The order ID to abort.

    Returns:
        True if abort succeeded, False otherwise.
    """
    log = get_logger()
    try:
        client.abort_order(order_id=order_id)
        log.info(f"🗑️  Order {order_id} aborted.")
        return True
    except Exception as e:
        log.warning(f"Could not abort order {order_id}: {e}")
        return False
