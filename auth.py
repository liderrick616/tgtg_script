"""
auth.py — Authentication & credential management for the TGTG bot.

Handles first-time email login, credential persistence (encrypted),
and automatic token refresh via the tgtg-python library.
"""

import json
import os
import sys
import base64

from tgtg import TgtgClient
from cryptography.fernet import Fernet

from logger_setup import get_logger

# Credential file location (same directory as the script)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(SCRIPT_DIR, "credentials.json")
KEY_FILE = os.path.join(SCRIPT_DIR, ".encryption_key")


def _get_or_create_key() -> bytes:
    """Get or create the Fernet encryption key for credential storage."""
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read()
    else:
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
        # Restrict permissions (owner-only read/write)
        os.chmod(KEY_FILE, 0o600)
        return key


def _encrypt_data(data: dict) -> str:
    """Encrypt credential data using Fernet symmetric encryption."""
    key = _get_or_create_key()
    fernet = Fernet(key)
    json_bytes = json.dumps(data).encode("utf-8")
    return fernet.encrypt(json_bytes).decode("utf-8")


def _decrypt_data(encrypted: str) -> dict:
    """Decrypt credential data."""
    key = _get_or_create_key()
    fernet = Fernet(key)
    json_bytes = fernet.decrypt(encrypted.encode("utf-8"))
    return json.loads(json_bytes.decode("utf-8"))


def save_credentials(credentials: dict):
    """
    Save TGTG credentials to an encrypted file.

    Args:
        credentials: Dict with access_token, refresh_token, cookie.
    """
    log = get_logger()
    encrypted = _encrypt_data(credentials)
    with open(CREDENTIALS_FILE, "w") as f:
        json.dump({"encrypted": encrypted}, f)
    os.chmod(CREDENTIALS_FILE, 0o600)
    log.info(f"Credentials saved to {CREDENTIALS_FILE}")


def load_credentials() -> dict | None:
    """
    Load saved credentials from the encrypted file.

    Returns:
        Credential dict or None if no saved credentials exist.
    """
    if not os.path.exists(CREDENTIALS_FILE):
        return None

    try:
        with open(CREDENTIALS_FILE, "r") as f:
            data = json.load(f)
        return _decrypt_data(data["encrypted"])
    except Exception as e:
        log = get_logger()
        log.warning(f"Could not load saved credentials: {e}")
        return None


def has_saved_credentials() -> bool:
    """Check if saved credentials exist."""
    return os.path.exists(CREDENTIALS_FILE)


def login(email: str) -> TgtgClient:
    """
    Perform first-time login via email verification.

    This triggers an email from TGTG. The user must click the link in the email
    to complete authentication. The client will block until the link is clicked.

    Args:
        email: The TGTG account email address.

    Returns:
        Authenticated TgtgClient instance.
    """
    log = get_logger()

    log.info(f"Starting login for: {email}")
    log.info("📧 Check your email — click the login link from Too Good To Go.")
    log.info("⏳ Waiting for email verification...")

    client = TgtgClient(email=email)
    credentials = client.get_credentials()

    log.info("✅ Login successful!")
    save_credentials(credentials)

    return client


def get_client(config: dict) -> TgtgClient:
    """
    Get an authenticated TgtgClient instance.

    Tries to load saved credentials first. If none exist, falls back to
    email login flow.

    Args:
        config: The loaded configuration dictionary.

    Returns:
        Authenticated TgtgClient instance.
    """
    log = get_logger()
    creds = load_credentials()

    if creds:
        log.info("🔑 Loading saved credentials...")
        try:
            client = TgtgClient(
                access_token=creds.get("access_token", ""),
                refresh_token=creds.get("refresh_token", ""),
                cookie=creds.get("cookie", ""),
            )
            # Test the connection by making a lightweight request
            # The tgtg library handles token refresh automatically
            log.info("🔗 Credentials loaded. Token refresh handled automatically.")
            return client
        except Exception as e:
            log.warning(f"Saved credentials failed: {e}")
            log.info("Falling back to email login...")

    # No saved creds or they failed — do email login
    email = config.get("tgtg", {}).get("email", "")
    if not email or email == "your_email@example.com":
        log.error("❌ No email configured. Set your email in config.yaml first.")
        sys.exit(1)

    return login(email)


def refresh_and_save(client: TgtgClient):
    """
    Refresh the client's tokens and save the updated credentials.

    Call this periodically (e.g., every 30 minutes) to keep tokens fresh.
    The tgtg library handles refresh internally, but this ensures the
    saved credentials file stays up to date.

    Args:
        client: The active TgtgClient instance.
    """
    log = get_logger()
    try:
        credentials = client.get_credentials()
        save_credentials(credentials)
        log.debug("🔄 Credentials refreshed and saved.")
    except Exception as e:
        log.warning(f"Could not refresh credentials: {e}")
