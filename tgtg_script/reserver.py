"""
reserver.py — Order reservation engine for the TGTG bot.

Handles creating reservations and monitoring order status.
"""

from tgtg import TgtgClient

from logger_setup import get_logger
from notifier import notify_stock_detected, notify_payment_result
from card_store import PaymentSetupError


def attempt_reserve(client: TgtgClient, config: dict, item_data: dict, payment=None) -> dict | None:
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
    auto_reserve = reservation_config.get("auto_reserve", False)
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

    if config.get("payment", {}).get("enabled", False) and payment is None:
        log.error("Automatic payment was requested but not initialized. Skipping reservation.")
        return None

    if payment is not None:
        try:
            if not payment.claim_reservation(item_data):
                log.debug("Skipping item: already attempted for this pickup window or run limit reached.")
                return None
        except PaymentSetupError as exc:
            log.warning("Skipping automatic purchase: %s", exc)
            return None
        except Exception:
            log.error("Could not save the duplicate guard. Skipping automatic purchase.")
            return None

    # Auto-reserve mode — try to lock the bag
    log.info(f"🎯 STOCK DETECTED at {store_name}! Attempting reservation...")
    log.info(f"   Item ID: {item_id} | Available: {available} | Reserving: {quantity}")

    try:
        order = client.create_order(item_id=item_id, item_count=quantity)
    except Exception as e:
        # A timeout may still have created an order. Keep the durable claim.
        log.error("Reservation could not be confirmed for %s. Check the TGTG app.", store_name)
        from payment import PaymentResult
        try:
            notify_payment_result(config, item_data, None, PaymentResult(
                "unknown", "Reservation could not be confirmed. Check the app before trying again."
            ))
        except Exception:
            log.warning("Could not deliver the reservation notification.")
        return None

    order_id = str(order.get("id", order.get("order_id", "unknown")))
    log.info("Reserved order %s.", order_id)
    # Payment/notification errors must not hide an already-created reservation.
    try:
        if payment is not None:
            result = payment.pay(order, item_data)
            log.info("Checkout %s: %s", result.status, result.message)
            notify_payment_result(config, item_data, order_id, result)
        else:
            notify_stock_detected(config, item_data, reserved=True, order_id=order_id)
    except Exception:
        log.error("Checkout or notification could not be confirmed. Check order %s in the app.", order_id)
    return order


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
        log.debug("Order status retrieved.")
        return status
    except Exception:
        log.warning("Could not check order status. Check the official app.")
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
    except Exception:
        log.warning("Could not confirm cancellation. Check the official app.")
        return False
