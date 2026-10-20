# TGTG Sniper Bot

A Python command-line tool for monitoring Too Good To Go favorites, with optional
reservation and experimental card payment. It uses an unofficial API and is not
affiliated with Too Good To Go.

**Live automatic payment has not been validated.** Offline tests exercise the
checkout logic, but do not establish that the current service accepts it.
API access can be denied by DataDome or other server restrictions. The bot stops
on access denial; updating this script does not remove a server-side block.

## Setup

Python 3.10 or newer is required. Saving a card requires macOS Keychain.
From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp config.example.yaml config.yaml
```

Edit `config.yaml` to set your account email. Keep this file private.

```bash
python3 main.py login
python3 main.py check-access
python3 main.py list-favorites
```

Follow the email verification flow during login. Add your desired item IDs to
`targets` in `config.yaml`, or enable `monitor_all_favorites`. Then run:

```bash
python3 main.py run --no-burst
```

The sample configuration only sends availability notifications. To reserve bags,
explicitly set `reservation.auto_reserve: true`. A reservation by itself is not a
completed purchase. See [PAYMENT_SETUP.md](PAYMENT_SETUP.md) for automatic payment.
Press Ctrl+C to stop.

## Commands

| Command | Purpose |
| --- | --- |
| `login` | Authenticate through email verification |
| `check-access` | Read favorites once, without card access or a purchase |
| `list-favorites` | Show favorite item IDs |
| `run` | Monitor configured targets |
| `test-notify` | Send a notification through enabled channels |
| `setup-payment` | Save a card in macOS Keychain |
| `payment-status` | Show local card setup, without charging |
| `forget-payment` | Delete the card saved for the configured account |

Use `python3 main.py --help` or `python3 main.py run --help` for options.
A custom configuration path goes before the command:
`python3 main.py --config path/to/private.yaml run`.

macOS notifications are enabled in the example. Telegram and Discord are
optional; their credentials belong only in your private configuration.
Notification content includes store and order information.

## Data and publishing

This source distribution contains blank settings and synthetic test data.
Never commit your working `config.yaml`, saved credentials, encryption key,
logs, captures, databases, or backups. `.gitignore` excludes common local files;
it cannot remove files that were committed previously.

Use a fresh repository when publishing a sanitized source copy. Review the
staged files before pushing. Copying clean files over an existing repository
does not erase its earlier commits. See [SECURITY.md](SECURITY.md) for storage
locations and cleanup guidance.

## Offline tests

```bash
python3 -m pip install pytest
python3 -m pytest -q
```

Tests use mock services, synthetic card details and generated encryption keys.
They do not make real reservations or payments.

Third-party attribution is in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
