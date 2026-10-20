"""Card setup in macOS Keychain. The CVV is never persisted."""

from dataclasses import dataclass
from datetime import date
from getpass import getpass, GetPassWarning
import json
import re
import sys
import warnings

SERVICE = "tgtg-sniper.payment-card.v1"


class PaymentSetupError(ValueError):
    """A safe, user-facing payment setup error (never contains card data)."""


@dataclass(repr=False)
class Card:
    number: str
    month: str
    year: str

    def __repr__(self):
        return f"Card(ending={self.number[-4:]})"

    @classmethod
    def validate(cls, number, month, year):
        number = re.sub(r"[ -]", "", str(number))
        if not re.fullmatch(r"[0-9]{12,19}", number):
            raise PaymentSetupError("Card number must contain 12–19 digits.")
        digits = [int(c) for c in number[::-1]]
        total = sum(d if i % 2 == 0 else (d * 2 - 9 if d > 4 else d * 2)
                    for i, d in enumerate(digits))
        if total % 10:
            raise PaymentSetupError("Card number failed its checksum. Check the digits.")
        if not re.fullmatch(r"[0-9]{1,2}", str(month)):
            raise PaymentSetupError("Expiry month must be 1–12.")
        if not re.fullmatch(r"[0-9]{4}", str(year)):
            raise PaymentSetupError("Use a four-digit expiry year.")
        month, year = int(month), int(year)
        today = date.today()
        if not 1 <= month <= 12 or (year, month) < (today.year, today.month):
            raise PaymentSetupError("The expiry date is invalid or the card has expired.")
        return cls(number, f"{month:02}", str(year))


def hidden_input(prompt):
    # getpass otherwise falls back to echoing input when no terminal is attached.
    with warnings.catch_warnings():
        warnings.simplefilter("error", GetPassWarning)
        try:
            return getpass(prompt).strip()
        except (GetPassWarning, EOFError):
            raise PaymentSetupError("Use an interactive terminal for card entry.") from None


def validate_cvv(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{3,4}", value):
        raise PaymentSetupError("CVV must contain 3 or 4 digits.")
    return value


def _keychain():
    if sys.platform != "darwin":
        raise PaymentSetupError("Card storage currently requires macOS Keychain.")
    try:
        # Explicit backend: never fall back to a plaintext keyring plugin.
        from keyring.backends.macOS import Keyring
        return Keyring()
    except ImportError:
        raise PaymentSetupError("Install dependencies: python3 -m pip install -r requirements.txt") from None


def _account(config):
    email = config.get("tgtg", {}).get("email", "").strip().lower()
    if not email or email in {"your_email@example.com", "your_real_email@example.com"}:
        raise PaymentSetupError("Set tgtg.email in config.yaml before setting up payment.")
    return email


def save_card(config, card):
    payload = json.dumps({"number": card.number, "month": card.month, "year": card.year})
    try:
        _keychain().set_password(SERVICE, _account(config), payload)
    except PaymentSetupError:
        raise
    except Exception:
        raise PaymentSetupError("Could not save the card. Unlock macOS Keychain and retry.") from None


def load_card(config):
    try:
        payload = _keychain().get_password(SERVICE, _account(config))
        if not payload:
            raise PaymentSetupError("No saved card. Run: python3 main.py setup-payment")
        data = json.loads(payload)
        return Card.validate(data["number"], data["month"], data["year"])
    except PaymentSetupError:
        raise
    except Exception:
        raise PaymentSetupError("Could not read the card. Unlock Keychain or run setup-payment again.") from None


def forget_card(config):
    try:
        backend, account = _keychain(), _account(config)
        if backend.get_password(SERVICE, account) is not None:
            backend.delete_password(SERVICE, account)
    except PaymentSetupError:
        raise
    except Exception:
        raise PaymentSetupError("Could not remove the saved card from Keychain.") from None


def setup_card(config):
    print("Card details are entered locally and saved in macOS Keychain.")
    print("CVV is requested at bot startup and kept only in memory for that run.")
    card = Card.validate(
        hidden_input("Card number (hidden): "),
        hidden_input("Expiry month (MM, hidden): "),
        hidden_input("Expiry year (YYYY, hidden): "),
    )
    save_card(config, card)
    print(f"Saved card ending {card.number[-4:]}. Automatic payment remains opt-in.")
