"""Opt-in, single-attempt checkout using the published TGTG v8 / Adyen flow.

This is an unofficial integration, not a promise of current server compatibility.
Unknown responses, challenges and ambiguous failures require checking the app.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import requests

from adyen_crypto import encrypt_card, parse_public_key
from card_store import Card, PaymentSetupError, hidden_input, load_card, validate_cvv
from payment_state import PaymentState

BASE_URL = "https://apptoogoodtogo.com/api/"
ADYEN_KEY_URL = "https://checkoutshopper-live.adyen.com/checkoutshopper/v1/clientKeys/"
# Public merchant client identifier from the published TGTG card implementation.
# This is NOT an API secret. The key endpoint was checked on 2026-10-20.
ADYEN_CLIENT_KEY = "live_VPX45BIMLFAIVARYVKEDNC7OXIFBRQZ5"
PAYMENT_SUCCESS = {"SUCCESS", "SUCCEEDED", "AUTHORIZED", "AUTHORISED", "CAPTURED", "PAID"}
PAYMENT_FAILURE = {"FAILED", "REFUSED", "DECLINED", "CANCELLED", "CANCELED", "ERROR", "EXPIRED"}
PAYMENT_ACTION = {
    "ACTION_REQUIRED", "REQUIRES_ACTION", "REDIRECTSHOPPER", "IDENTIFYSHOPPER",
    "CHALLENGESHOPPER", "PRESENTTOSHOPPER",
}
PAYMENT_PENDING = {"PENDING", "CREATED", "PROCESSING", "RECEIVED"}
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")


@dataclass(frozen=True)
class PaymentResult:
    status: str
    message: str


def validate_settings(config):
    settings = config.get("payment", {})
    try:
        maximum = Decimal(str(settings.get("max_order_total", "")))
        if not maximum.is_finite() or maximum <= 0:
            raise ValueError
    except (ValueError, InvalidOperation):
        raise PaymentSetupError("Set a positive payment.max_order_total or pass --max-total.") from None
    currency = settings.get("currency", "")
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise PaymentSetupError("Set a three-letter payment.currency or pass --currency (for example CAD).")
    max_orders = settings.get("max_orders_per_run", 1)
    if type(max_orders) is not int or not 1 <= max_orders <= 100:
        raise PaymentSetupError("payment.max_orders_per_run must be an integer from 1 to 100.")
    if config.get("reservation", {}).get("auto_reserve", True) is not True:
        raise PaymentSetupError("Automatic payment requires reservation.auto_reserve: true.")
    quantity = config.get("reservation", {}).get("quantity", 1)
    if type(quantity) is not int or not 1 <= quantity <= 100:
        raise PaymentSetupError("reservation.quantity must be an integer from 1 to 100.")
    return maximum, currency, max_orders


def money(value):
    if not isinstance(value, dict):
        raise PaymentSetupError("The server did not provide a usable total price.")
    units, decimals, code = (value.get(k) for k in ("minor_units", "decimals", "code"))
    if (type(units) is not int or units <= 0 or type(decimals) is not int
            or not 0 <= decimals <= 4 or not isinstance(code, str)
            or not re.fullmatch(r"[A-Z]{3}", code)):
        raise PaymentSetupError("The server returned an invalid price or currency.")
    return Decimal(units) / (Decimal(10) ** decimals), code


def _payment_records(body):
    if not isinstance(body, dict):
        return []
    if isinstance(body.get("payments"), list):
        return body["payments"]
    if isinstance(body.get("payment"), dict):
        return [body["payment"]]
    if body.get("payment_id"):
        return [body]
    return []


def _needs_action(record):
    if record.get("action") or record.get("redirect_url"):
        return True
    payload = record.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return bool(payload)  # Unrecognized provider data is not payment success.
    if isinstance(payload, dict):
        code = str(payload.get("resultCode", "")).upper()
        return bool(payload.get("action")) or code in PAYMENT_ACTION
    return False


def _provider_result(record):
    payload = record.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return ""
    return str(payload.get("resultCode", "")).upper() if isinstance(payload, dict) else ""


class PaymentService:
    def __init__(self, client, config, card, cvv, state, public_key, session=None):
        self.maximum, self.currency, self.max_orders = validate_settings(config)
        self.client, self.config, self.state = client, config, state
        self.card = Card.validate(card.number, card.month, card.year)
        self.cvv = validate_cvv(cvv)
        parse_public_key(public_key)
        self.public_key = public_key
        self.session = session or requests.Session()  # default: no HTTP retries
        self.attempts = 0

    def close(self):
        self.cvv = None
        self.card = None
        self.session.close()
        self.state.close()

    def claim_reservation(self, item):
        if self.attempts >= self.max_orders:
            return False
        item_id = str(item.get("item", {}).get("item_id", ""))
        pickup = item.get("pickup_interval", {}).get("start")
        if not SAFE_ID.fullmatch(item_id) or not isinstance(pickup, str) or not pickup:
            raise PaymentSetupError("Missing item ID or pickup window; reserve and pay in the app.")
        price = item.get("item", {}).get("price_including_taxes")
        if price is None:
            price = item.get("item", {}).get("item_price")
        amount, currency = money(price)
        quantity = self.config.get("reservation", {}).get("quantity", 1)
        if currency != self.currency or amount * quantity > self.maximum:
            raise PaymentSetupError("The item exceeds the order limit or uses a different currency.")
        if not self.state.claim_reservation(item_id, pickup):
            return False
        self.attempts += 1
        return True

    def _post(self, path, payload=None):
        # Use the existing authenticated account, but no library retry on payment.
        if self.client.base_url.rstrip("/") != BASE_URL.rstrip("/"):
            raise PaymentSetupError("Payment is restricted to the TGTG API host.")
        self.client.login()
        url = BASE_URL + path
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "apptoogoodtogo.com":
            raise PaymentSetupError("Unexpected payment API destination.")
        self.session.cookies.update(self.client.session.cookies)
        response = self.session.post(
            url, headers=self.client._headers, json=payload,
            proxies=self.client.proxies, timeout=(10, 20), allow_redirects=False,
        )
        if response.status_code != 200:
            # Never include response bodies: they can contain payment credentials.
            raise PaymentSetupError(f"TGTG payment API returned HTTP {response.status_code}.")
        body = response.json()
        if not isinstance(body, dict):
            raise PaymentSetupError("TGTG returned an unrecognized payment response.")
        return body

    def _classify(self, body, order_id, payment_id=None):
        records = _payment_records(body)
        # This implementation submits one full payment, never split payments.
        if len(records) != 1 or not isinstance(records[0], dict):
            return PaymentResult("unknown", "Unrecognized checkout response; check the order in the TGTG app.")
        record = records[0]
        pid = record.get("payment_id")
        if (record.get("order_id") != order_id or not isinstance(pid, str)
                or not SAFE_ID.fullmatch(pid) or (payment_id and pid != payment_id)):
            return PaymentResult("unknown", "Payment identifiers did not match; check the TGTG app.")
        status = str(record.get("state", "")).upper()
        if _needs_action(record) or status in PAYMENT_ACTION:
            return PaymentResult("action_required", "Bank verification is required. Open the TGTG app.")
        provider_status = _provider_result(record)
        if status in PAYMENT_FAILURE or provider_status in PAYMENT_FAILURE:
            return PaymentResult("failed", "Payment was declined or failed. Check the order in the TGTG app.")
        if status in PAYMENT_SUCCESS and provider_status in PAYMENT_SUCCESS | {""}:
            return PaymentResult("paid", "Payment confirmed by TGTG. Check the app for pickup details.")
        if status in PAYMENT_PENDING:
            return PaymentResult("pending", "Payment is processing.")
        return PaymentResult("unknown", "Payment status is unrecognized. Check the TGTG app before paying again.")

    def pay(self, order, item):
        order_id = str(order.get("id", order.get("order_id", "")))
        item_id = str(item.get("item", {}).get("item_id", ""))
        submitted = False
        try:
            if not SAFE_ID.fullmatch(order_id) or str(order.get("item_id", "")) != item_id:
                raise PaymentSetupError("The reserved order does not match the requested item.")
            self.state.record_reservation(item_id, item["pickup_interval"]["start"], order_id)
            if order.get("state") != "RESERVED":
                raise PaymentSetupError("The order is not awaiting payment. Check the TGTG app.")
            line = order.get("order_line", {})
            if (type(line.get("quantity")) is not int
                    or line["quantity"] != self.config.get("reservation", {}).get("quantity", 1)):
                raise PaymentSetupError("The reserved quantity does not match your settings.")
            amount = line.get("total_price_including_taxes")
            total, currency = money(amount)
            if currency != self.currency or total > self.maximum:
                raise PaymentSetupError("The final order total exceeds your limit or currency setting.")
            # Refresh expiration validation when a bot has been running for days.
            card = Card.validate(self.card.number, self.card.month, self.card.year)
            encrypted = encrypt_card(card, self.cvv, self.public_key)
            payload = {"authorizations": [{
                "amount": {k: amount[k] for k in ("code", "minor_units", "decimals")},
                "authorization_payload": {
                    "payload": json.dumps(encrypted, separators=(",", ":")),
                    "payment_type": "CREDITCARD",
                    "save_payment_method": False,
                    "type": "adyenAuthorizationPayload",
                },
                "payment_provider": "ADYEN",
                "return_url": "adyencheckout://com.app.tgtg.itemview",
            }]}
            if not self.state.claim_payment(order_id):
                return PaymentResult("unknown", "Payment was already attempted for this order. Check the app.")
            submitted = True
            body = self._post(f"order/v8/{order_id}/pay", payload)
            result = self._classify(body, order_id)
            if result.status == "pending":
                payment_id = _payment_records(body)[0]["payment_id"]
                # Read-only status polling is safe; never repeat the payment POST.
                for _ in range(5):
                    time.sleep(2)
                    body = self._post(f"payment/v4/{payment_id}")
                    result = self._classify(body, order_id, payment_id)
                    if result.status != "pending":
                        break
            if result.status == "pending":
                result = PaymentResult("unknown", "Payment is still processing. Check the app before paying again.")
            self.state.record_payment(order_id, result.status)
            return result
        except PaymentSetupError as exc:
            if not submitted:
                return PaymentResult("not_attempted", str(exc))
            return PaymentResult("unknown", "Checkout could not be confirmed. Check the app before paying again.")
        except Exception:
            # Includes timeouts, corrupt responses and state-storage errors.
            # No raw exception repr: requests/errors can include submitted data.
            return PaymentResult(
                "unknown" if submitted else "not_attempted",
                "Checkout could not be confirmed. Check the order in the TGTG app.",
            )


def prepare_payment(client, config):
    validate_settings(config)
    card = load_card(config)
    session = requests.Session()
    state = None
    try:
        response = session.get(ADYEN_KEY_URL + ADYEN_CLIENT_KEY,
                               timeout=(10, 20), allow_redirects=False)
        if response.status_code != 200:
            raise PaymentSetupError("Adyen encryption key is unavailable; auto-payment cannot start.")
        public_key = response.json()["publicKey"]
        parse_public_key(public_key)
        cvv = validate_cvv(hidden_input(f"CVV for card ending {card.number[-4:]} (hidden, this run only): "))
        path = Path(config["payment"]["state_file"]).expanduser()
        state = PaymentState(path, config["tgtg"]["email"])
        return PaymentService(client, config, card, cvv, state, public_key, session)
    except BaseException as exc:
        session.close()
        if state is not None:
            state.close()
        if isinstance(exc, (PaymentSetupError, KeyboardInterrupt)):
            raise
        raise PaymentSetupError("Payment setup failed. Check network access and the payment state file.") from None
