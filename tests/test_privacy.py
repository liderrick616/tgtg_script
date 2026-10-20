"""Regression tests for secret-free diagnostics; all values are synthetic."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

import auth
import main
import notifier
from api_client import APIAccessError
from config_loader import load_config
from logger_setup import setup_logger


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("Network must not be used in offline tests")
    monkeypatch.setattr(requests.Session, "request", blocked)
    for module in (auth, notifier):
        monkeypatch.setattr(module, "get_logger", lambda: logging.getLogger("privacy-test"))


@pytest.mark.parametrize("channel", ["telegram", "discord"])
@pytest.mark.parametrize("failure", ["exception", "response"])
def test_notification_failures_do_not_log_secrets(channel, failure, monkeypatch, caplog):
    private = "SYNTHETIC_PRIVATE_VALUE"
    post = Mock()
    if failure == "exception":
        post.side_effect = requests.ConnectionError(f"https://example.com/{private}")
    else:
        post.return_value = SimpleNamespace(status_code=403, text=private)
    monkeypatch.setattr(notifier.requests, "post", post)
    if channel == "telegram":
        notifier._notify_telegram({"bot_token": private, "chat_id": "test"}, "test", "test")
    else:
        notifier._notify_discord({"webhook_url": f"https://example.com/{private}"}, "test", "test")
    assert "403" in caplog.text or "notification failed" in caplog.text
    assert private not in caplog.text


def test_login_failure_does_not_expose_account_or_response(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    private = "SYNTHETIC_PRIVATE_RESPONSE"
    client = Mock()
    client.get_credentials.side_effect = RuntimeError(private)
    monkeypatch.setattr(auth, "TgtgClient", Mock(return_value=client))
    with pytest.raises(APIAccessError) as error:
        auth.login("test-user@example.com")
    assert private not in str(error.value)
    assert private not in caplog.text
    assert "test-user@example.com" not in caplog.text


def test_favorites_uses_safe_error_without_response(monkeypatch):
    client = Mock()
    client.get_items.side_effect = RuntimeError("SYNTHETIC_PRIVATE_RESPONSE")
    monkeypatch.setattr(main, "has_saved_credentials", lambda: True)
    monkeypatch.setattr(main, "get_client", lambda _: client)
    with pytest.raises(APIAccessError) as error:
        main.cmd_list_favorites(None, {})
    assert "SYNTHETIC_PRIVATE_RESPONSE" not in str(error.value)


def test_new_configuration_requires_explicit_reservation_and_payment(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("{}")
    config = load_config(str(config_file))
    assert config["reservation"]["auto_reserve"] is False
    assert config["payment"]["enabled"] is False
    assert config["logging"]["file"] is None


def test_default_logger_does_not_create_a_log_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    logger = setup_logger()
    logger.info("Local diagnostic")
    assert not list(tmp_path.iterdir())
    assert not any(isinstance(handler, logging.FileHandler) for handler in logger.handlers)
