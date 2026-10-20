"""Offline checkout tests. No network access, account credentials or real cards."""

import base64
import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

import card_store
from card_store import Card, PaymentSetupError
from adyen_crypto import encrypt_card
from payment import BASE_URL, PaymentResult, PaymentService, validate_settings
from payment_state import PaymentState
import reserver


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in the offline test suite")
    monkeypatch.setattr(requests.Session, "request", blocked)
    monkeypatch.setattr(reserver, "get_logger", lambda: logging.getLogger("test"))


@pytest.fixture(scope="module")
def keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private.public_key().public_numbers()
    return private, f"{numbers.e:x}|{numbers.n:x}"


@pytest.fixture
def config(tmp_path):
    return {
        "tgtg": {"email": "offline@example.com"},
        "reservation": {"auto_reserve": True, "quantity": 1},
        "payment": {"enabled": True, "max_order_total": "10.00", "currency": "CAD",
                    "max_orders_per_run": 2, "state_file": str(tmp_path / "state.sqlite3")},
    }


@pytest.fixture
def item():
    return {
        "item": {"item_id": "123", "price_including_taxes":
                 {"minor_units": 599, "decimals": 2, "code": "CAD"}},
        "store": {"store_name": "Offline Bakery"},
        "items_available": 1,
        "pickup_interval": {"start": "2099-11-01T15:00:00Z"},
    }


@pytest.fixture
def order():
    return {
        "id": "order-1", "item_id": "123", "state": "RESERVED",
        "order_line": {"quantity": 1, "total_price_including_taxes":
                       {"minor_units": 677, "decimals": 2, "code": "CAD"}},
    }


def response(state="SUCCESS", **kwargs):
    return {"payments": [{"payment_id": "pay-1", "order_id": "order-1",
                          "state": state, **kwargs}]}


@pytest.fixture
def service(config, keys):
    client = SimpleNamespace(
        base_url=BASE_URL, login=Mock(), _headers={"authorization": "Bearer fake"},
        session=SimpleNamespace(cookies=requests.cookies.RequestsCookieJar()), proxies=None,
    )
    session = Mock()
    session.cookies = requests.cookies.RequestsCookieJar()
    session.post.return_value = SimpleNamespace(status_code=200, json=lambda: response())
    state = PaymentState(config["payment"]["state_file"], config["tgtg"]["email"])
    result = PaymentService(client, config, Card.validate("4111111111111111", "12", "2099"),
                            "737", state, keys[1], session)
    yield result
    result.close()


def test_crypto_round_trip_and_freshness(keys):
    card = Card.validate("4111111111111111", "12", "2099")
    encrypted = encrypt_card(card, "737", keys[1])
    fields = {"encryptedCardNumber": ("number", card.number),
              "encryptedExpiryMonth": ("expiryMonth", "12"),
              "encryptedExpiryYear": ("expiryYear", "2099"),
              "encryptedSecurityCode": ("cvc", "737")}
    for output, (name, value) in fields.items():
        version, wrapped, ciphertext = encrypted[output].split("$")
        assert version == "adyenjs_0_1_1"
        aes = keys[0].decrypt(base64.b64decode(wrapped), padding.PKCS1v15())
        data = base64.b64decode(ciphertext)
        plain = json.loads(AESCCM(aes, tag_length=8).decrypt(data[:12], data[12:], None))
        assert plain[name] == value
        assert plain["generationtime"].endswith("Z")
    assert encrypt_card(card, "737", keys[1]) != encrypted
    assert card.number not in repr(card)


def test_final_tax_inclusive_total_and_encrypted_fields(service, item, order):
    assert service.claim_reservation(item)
    result = service.pay(order, item)
    assert result.status == "paid"
    args, kwargs = service.session.post.call_args
    assert args == (BASE_URL + "order/v8/order-1/pay",)
    payload = kwargs["json"]
    assert payload["authorizations"][0]["amount"]["minor_units"] == 677
    assert "4111111111111111" not in json.dumps(payload)
    inner = json.loads(payload["authorizations"][0]["authorization_payload"]["payload"])
    assert inner["encryptedSecurityCode"].startswith("adyenjs_0_1_1$")
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == (10, 20)


@pytest.mark.parametrize("state,expected", [
    ("SUCCESS", "paid"), ("AUTHORIZED", "paid"), ("FAILED", "failed"),
    ("REFUSED", "failed"), ("ACTION_REQUIRED", "action_required"),
    ("SOMETHING_NEW", "unknown"),
])
def test_explicit_status(service, item, order, state, expected):
    service.session.post.return_value.json = lambda: response(state)
    assert service.pay(order, item).status == expected
    assert service.session.post.call_count == 1


def test_challenge_wins_over_success(service, item, order):
    service.session.post.return_value.json = lambda: response(
        payload=json.dumps({"action": {"type": "threeDS2"}, "resultCode": "ChallengeShopper"})
    )
    assert service.pay(order, item).status == "action_required"


def test_provider_decline_wins_over_success(service, item, order):
    service.session.post.return_value.json = lambda: response(payload={"resultCode": "Refused"})
    assert service.pay(order, item).status == "failed"


@pytest.mark.parametrize("body", [
    {"state": "SUCCESS"}, {}, {"payments": []},
    response(order_id="wrong-order"),
    {"payments": response()["payments"] * 2},
])
def test_unknown_or_mismatched_response_is_not_success(service, item, order, body):
    service.session.post.return_value.json = lambda: body
    assert service.pay(order, item).status == "unknown"


def test_pending_polls_status_without_reposting_payment(service, item, order, monkeypatch):
    monkeypatch.setattr("payment.time.sleep", lambda _: None)
    service.session.post.side_effect = [
        SimpleNamespace(status_code=200, json=lambda: response("PENDING")),
        SimpleNamespace(status_code=200, json=lambda: response()),
    ]
    assert service.pay(order, item).status == "paid"
    assert [c.args[0] for c in service.session.post.call_args_list] == [
        BASE_URL + "order/v8/order-1/pay", BASE_URL + "payment/v4/pay-1"
    ]


def test_pending_deadline(service, item, order, monkeypatch):
    monkeypatch.setattr("payment.time.sleep", lambda _: None)
    service.session.post.return_value.json = lambda: response("PENDING")
    assert service.pay(order, item).status == "unknown"
    assert service.session.post.call_count == 6


@pytest.mark.parametrize("error", [requests.Timeout("secret"), requests.ConnectionError("secret")])
def test_ambiguous_failure_is_never_retried(service, item, order, error):
    service.session.post.side_effect = error
    result = service.pay(order, item)
    assert result.status == "unknown"
    assert "secret" not in result.message
    assert service.pay(order, item).status == "unknown"
    assert service.session.post.call_count == 1


@pytest.mark.parametrize("status", [302, 400, 401, 403, 429, 500])
def test_http_failures_never_retry_or_follow_redirect(service, item, order, status):
    service.session.post.return_value.status_code = status
    assert service.pay(order, item).status == "unknown"
    assert service.session.post.call_count == 1


@pytest.mark.parametrize("change", ["price", "currency", "quantity", "id", "state", "missing_total"])
def test_invalid_order_never_submits_payment(service, item, order, change):
    if change == "price":
        order["order_line"]["total_price_including_taxes"]["minor_units"] = 1001
    elif change == "currency":
        order["order_line"]["total_price_including_taxes"]["code"] = "USD"
    elif change == "quantity":
        order["order_line"]["quantity"] = 2
    elif change == "id":
        order["item_id"] = "999"
    elif change == "state":
        order["state"] = "CANCELLED"
    else:
        order["order_line"].pop("total_price_including_taxes")
    assert service.pay(order, item).status == "not_attempted"
    service.session.post.assert_not_called()


def test_ledger_survives_restart_and_handles_concurrent_instances(config):
    a = PaymentState(config["payment"]["state_file"], "offline@example.com")
    b = PaymentState(config["payment"]["state_file"], "offline@example.com")
    assert a.claim_reservation("123", "pickup-1")
    assert not b.claim_reservation("123", "pickup-1")
    assert a.claim_payment("order-1")
    a.close()
    assert not b.claim_payment("order-1")
    assert b.claim_reservation("123", "pickup-2")
    assert b.db.execute("SELECT outcome FROM payments").fetchone() == ("submitted",)
    b.close()


def test_reservation_run_cap_and_duplicate_window(service, item):
    assert service.claim_reservation(item)
    assert not service.claim_reservation(item)
    item["pickup_interval"]["start"] = "2099-11-02T15:00:00Z"
    assert service.claim_reservation(item)
    item["pickup_interval"]["start"] = "2099-11-03T15:00:00Z"
    assert not service.claim_reservation(item)


@pytest.mark.parametrize("maximum", ["", None, "nan", "Infinity", "-1", "0"])
def test_bad_limits(config, maximum):
    config["payment"]["max_order_total"] = maximum
    with pytest.raises(PaymentSetupError):
        validate_settings(config)


def test_reservation_survives_notification_failure(config, item, order, monkeypatch):
    client = Mock()
    client.create_order.return_value = order
    payment = Mock()
    payment.claim_reservation.return_value = True
    payment.pay.return_value = PaymentResult("paid", "Confirmed")
    monkeypatch.setattr(reserver, "notify_payment_result", Mock(side_effect=RuntimeError))
    assert reserver.attempt_reserve(client, config, item, payment) == order
    client.create_order.assert_called_once_with(item_id="123", item_count=1)
    payment.pay.assert_called_once_with(order, item)


def test_disabled_payment_keeps_manual_flow(config, item, order, monkeypatch):
    config["payment"]["enabled"] = False
    client = Mock()
    client.create_order.return_value = order
    notify = Mock()
    monkeypatch.setattr(reserver, "notify_stock_detected", notify)
    assert reserver.attempt_reserve(client, config, item) == order
    notify.assert_called_once_with(config, item, reserved=True, order_id="order-1")


def test_uninitialized_payment_never_reserves(config, item):
    client = Mock()
    assert reserver.attempt_reserve(client, config, item) is None
    client.create_order.assert_not_called()


def test_card_store_does_not_persist_cvv(config, monkeypatch):
    backend = Mock()
    monkeypatch.setattr(card_store, "_keychain", lambda: backend)
    card_store.save_card(config, Card.validate("4111111111111111", "12", "2099"))
    payload = json.loads(backend.set_password.call_args.args[2])
    assert set(payload) == {"number", "month", "year"}


@pytest.mark.parametrize("number,month,year", [
    ("4111111111111112", "12", "2099"), ("not-a-card", "12", "2099"),
    ("4111111111111111", "13", "2099"), ("4111111111111111", "12", "2000"),
])
def test_invalid_cards(number, month, year):
    with pytest.raises(PaymentSetupError):
        Card.validate(number, month, year)


def test_untrusted_api_host_receives_no_card(service, item, order):
    service.client.base_url = "https://example.org/api/"
    assert service.pay(order, item).status == "unknown"
    service.session.post.assert_not_called()


def test_secret_input_never_falls_back_to_echo(monkeypatch):
    import warnings
    def unsafe_getpass(prompt):
        warnings.warn("Cannot hide input", card_store.GetPassWarning)
        pytest.fail("An echoing prompt must not be reached")
    monkeypatch.setattr(card_store, "getpass", unsafe_getpass)
    with pytest.raises(PaymentSetupError, match="interactive terminal"):
        card_store.hidden_input("Card: ")


def test_reservation_failure_never_attempts_payment(config, item, monkeypatch):
    client, payment = Mock(), Mock()
    client.create_order.side_effect = requests.Timeout("sensitive response data")
    payment.claim_reservation.return_value = True
    notify = Mock()
    monkeypatch.setattr(reserver, "notify_payment_result", notify)
    assert reserver.attempt_reserve(client, config, item, payment) is None
    payment.pay.assert_not_called()
    assert notify.call_args.args[3].status == "unknown"
    assert "sensitive" not in notify.call_args.args[3].message


def test_successful_payment_notification_has_no_pay_instruction(config, item, monkeypatch):
    import notifier
    notify = Mock()
    monkeypatch.setattr(notifier, "notify_all", notify)
    notifier.notify_payment_result(config, item, "order-1", PaymentResult("paid", "Payment confirmed."))
    assert notify.call_args.kwargs["title"] == "BAG PURCHASED"
    assert "tap PAY" not in notify.call_args.args[1]


@pytest.mark.parametrize("variation", ["too_expensive", "wrong_currency", "missing_pickup"])
def test_ineligible_item_never_claims_reservation(service, item, variation):
    if variation == "too_expensive":
        item["item"]["price_including_taxes"]["minor_units"] = 1001
    elif variation == "wrong_currency":
        item["item"]["price_including_taxes"]["code"] = "USD"
    else:
        item.pop("pickup_interval")
    with pytest.raises(PaymentSetupError):
        service.claim_reservation(item)
    assert service.state.db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] == 0


def test_journal_write_failure_blocks_payment(service, item, order, monkeypatch):
    monkeypatch.setattr(service.state, "claim_payment", Mock(side_effect=OSError("disk full")))
    assert service.pay(order, item).status == "not_attempted"
    service.session.post.assert_not_called()


def test_enabling_config_is_a_boolean(tmp_path):
    from config_loader import load_config
    path = tmp_path / "config.yaml"
    path.write_text('payment:\n  enabled: "false"\n')
    with pytest.raises(ValueError, match="without quotes"):
        load_config(str(path))
