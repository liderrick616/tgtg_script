from datetime import datetime
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from tgtg.exceptions import TgtgAPIError

import main
import poller
from api_client import APIAccessError, TgtgClient, access_message, check_access, http_status


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("Network must not be used in offline tests")
    monkeypatch.setattr(requests.Session, "request", blocked)
    monkeypatch.setattr(main, "get_logger", lambda: logging.getLogger("test"))
    monkeypatch.setattr(poller, "get_logger", lambda: logging.getLogger("test"))
    monkeypatch.setattr(poller.signal, "signal", Mock())


def test_denial_transport_never_retries_or_generates_fingerprints():
    client = SimpleNamespace(
        session=Mock(), _headers={"authorization": "Bearer fake"}, proxies=None,
        timeout=20, _ensure_datadome_cookie=Mock(), _fetch_datadome_cookie=Mock(),
    )
    client.session.post.return_value.status_code = 403
    response = TgtgClient._post(client, "https://apptoogoodtogo.com/api/item/v8/", json={})
    assert response.status_code == 403
    client.session.post.assert_called_once()
    client._ensure_datadome_cookie.assert_not_called()
    client._fetch_datadome_cookie.assert_not_called()
    assert client.session.post.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("error,expected", [
    (TgtgAPIError(403, b"forbidden"), 403),
    (TgtgAPIError(401, b"expired"), 401),
    (TgtgAPIError(429, b"rate limited"), 429),
    (RuntimeError("order 403123 not available"), None),
    (RuntimeError("Forbidden item name"), None),
])
def test_status_uses_code_not_body_substring(error, expected):
    assert http_status(error) == expected


def test_requests_http_error_detected():
    response = requests.Response()
    response.status_code = 403
    assert http_status(requests.HTTPError(response=response)) == 403


def test_challenge_label_requires_evidence_and_never_leaks_response():
    assert "DataDome" not in access_message(TgtgAPIError(403, b"access denied"))
    message = access_message(TgtgAPIError(403, b'{"url":"https://geo.captcha-delivery.com/?secret=TOKEN"}'))
    assert "DataDome" in message
    assert "TOKEN" not in message
    assert "https://" not in message


@pytest.mark.parametrize("start,end,time,expected", [
    ("0:00", "11:59", "02:12", True),
    ("00:00", "11:59", "02:12", True),
    ("0:00", "11:59", "12:00", False),
    ("21:10", "21:59", "21:10", True),
    ("21:10", "21:59", "22:00", False),
    ("23:00", "01:00", "00:30", True),
    ("23:00", "01:00", "23:30", True),
    ("23:00", "01:00", "12:30", False),
    ("bad", "11:59", "02:12", False),
    ("24:00", "11:59", "02:12", False),
    (0, "11:59", "02:12", False),
])
def test_numeric_time_windows(start, end, time, expected):
    now = datetime.strptime(time, "%H:%M")
    assert poller._is_in_burst_window([{"start": start, "end": end}], now=now) is expected


@pytest.fixture
def config():
    return {
        "tgtg": {"email": "offline@example.com"},
        "targets": [{"item_id": "123"}],
        "reservation": {"auto_reserve": True, "quantity": 1},
        "payment": {"enabled": False, "max_order_total": "15", "currency": "CAD"},
        "polling": {"burst_windows": [{"start": "0:00", "end": "11:59"}]},
    }


@pytest.fixture
def args():
    return SimpleNamespace(auto_pay=True, no_burst=False, max_total=None, currency=None)


def test_blocked_startup_never_prompts_for_cvv(config, args, monkeypatch):
    client = Mock()
    client.get_items.side_effect = TgtgAPIError(403, b"sensitive body")
    monkeypatch.setattr(main, "has_saved_credentials", lambda: True)
    monkeypatch.setattr(main, "get_client", lambda _: client)
    setup, poll = Mock(), Mock()
    monkeypatch.setattr(main, "prepare_payment", setup)
    monkeypatch.setattr(main, "run_polling_loop", poll)
    with pytest.raises(APIAccessError, match="403"):
        main.cmd_run(args, config)
    client.get_items.assert_called_once_with(favorites_only=True)
    setup.assert_not_called()
    poll.assert_not_called()


def test_startup_orders_access_then_card_setup_and_reuses_result(config, args, monkeypatch):
    events, items = [], [{"item": {"item_id": "123"}}]
    client, payment = Mock(), Mock()
    client.get_items.side_effect = lambda **_: (events.append("access") or items)
    monkeypatch.setattr(main, "has_saved_credentials", lambda: True)
    monkeypatch.setattr(main, "get_client", lambda _: client)
    monkeypatch.setattr(main, "prepare_payment", lambda *args: (events.append("card") or payment))
    poll = Mock(return_value=True)
    monkeypatch.setattr(main, "run_polling_loop", poll)
    main.cmd_run(args, config)
    assert events == ["access", "card"]
    poll.assert_called_once_with(client, config, payment=payment, initial_items=items)
    payment.close.assert_called_once()


def test_no_burst_option_keeps_original_schedule_object(config, args, monkeypatch):
    original = config["polling"]
    args.no_burst = True
    monkeypatch.setattr(main, "has_saved_credentials", lambda: True)
    client = Mock()
    client.get_items.side_effect = TgtgAPIError(403, b"blocked")
    monkeypatch.setattr(main, "get_client", lambda _: client)
    with pytest.raises(APIAccessError):
        main.cmd_run(args, config)
    assert config["polling"]["burst_windows"] == []
    assert original["burst_windows"] != []


@pytest.mark.parametrize("code", [401, 403])
def test_polling_stops_on_denial_without_cooldown_retry(config, code, monkeypatch):
    client = Mock()
    client.get_items.side_effect = TgtgAPIError(code, b"blocked")
    sleep, reserve = Mock(), Mock()
    monkeypatch.setattr(poller, "_sleep_with_interrupt", sleep)
    monkeypatch.setattr(poller, "attempt_reserve", reserve)
    assert poller.run_polling_loop(client, config) is False
    client.get_items.assert_called_once()
    sleep.assert_not_called()
    reserve.assert_not_called()


def test_preflight_result_is_not_fetched_twice(config, monkeypatch):
    client = Mock()
    def stop(_):
        poller._shutdown_requested = True
    monkeypatch.setattr(poller, "_sleep_with_interrupt", stop)
    assert poller.run_polling_loop(client, config, initial_items=[]) is True
    client.get_items.assert_not_called()


def test_read_only_check_does_not_purchase():
    client = Mock()
    client.get_items.return_value = []
    assert check_access(client) == []
    client.create_order.assert_not_called()


def test_check_access_cli_does_not_read_card(config, monkeypatch):
    client = Mock()
    client.get_items.return_value = []
    monkeypatch.setattr(main, "has_saved_credentials", lambda: True)
    monkeypatch.setattr(main, "get_client", lambda _: client)
    setup, card = Mock(), Mock()
    monkeypatch.setattr(main, "prepare_payment", setup)
    monkeypatch.setattr(main, "load_card", card)
    main.cmd_check_access(SimpleNamespace(), config)
    setup.assert_not_called()
    card.assert_not_called()
    client.create_order.assert_not_called()
