# Experimental automatic payment

Automatic payment requires working API access, an explicit spending limit,
a saved card, and automatic reservation enabled. Live checkout compatibility is
unverified. Bank challenges and uncertain results require checking the official app.

## Configure

First follow the README to create your private `config.yaml` and authenticate.
Set `reservation.auto_reserve: true` in that file, then run:

```bash
python3 main.py check-access
python3 main.py setup-payment
```

Enter card number and expiry in the hidden terminal prompts. These are stored in
macOS Keychain under service `tgtg-sniper.payment-card.v1`, associated with the
configured email. CVV is never saved.

Choose a maximum final order total and currency. For example:

```bash
python3 main.py run --auto-pay --max-total 15.00 --currency CAD --no-burst
```

This example permits one reservation attempt this run, up to 15.00 CAD including
tax. CVV is prompted once after the API access check and kept in process memory
until exit. Never put card details or CVV into source code, YAML, shell commands,
issue reports or logs.

You can instead opt in through private configuration:

```yaml
reservation:
  auto_reserve: true
  quantity: 1
payment:
  enabled: true
  max_order_total: "15.00"
  currency: "CAD"
  max_orders_per_run: 1
```

The order allowance counts reservation attempts, including uncertain failures.
The maximum potential spend per run is the order limit times that allowance.
All-favorites mode permits the first eligible available favorite to consume it.

## Outcomes

- The bot checks final amount, currency, item and quantity before submitting.
- Each payment is submitted once. Pending status can be checked up to five times.
- An HTTP 200 alone is not success; an explicit supported success state is required.
- A timeout, bank challenge, decline or unknown response requires checking the app.
  Inspect the existing order before attempting payment again.
- A persistent database guards against repeating the same item/pickup-window
  reservation or order payment after a restart.

The default guard database is
`~/Library/Application Support/TGTG Sniper/payment_state.sqlite3`. It stores hashed
account identity and order/item metadata, with no card details. Deleting it
removes duplicate protection. Do not delete it to retry an uncertain purchase.

## Remove a card

While the account email is still configured:

```bash
python3 main.py forget-payment
```

Stop every running bot to release its in-memory card and CVV references.
See [SECURITY.md](SECURITY.md) for the other local data locations.

## Access denied

A 401 or 403 stops the bot before the CVV prompt. Check account access in the
official app. Working app access does not prove that script access is allowed.
`check-access` performs one read-only request; it does not bypass verification.
The CLI reports the error without the former `NameError` traceback.

## Implementation

The implementation uses the unofficial TGTG v8 payment flow and legacy Adyen
client-side encryption. The merchant client identifier in `payment.py` is a public
integration identifier, not a user credential. Offline tests validate local
behavior, not server acceptance or bank approval.

Source references:

- [tgtg-python](https://github.com/ahivert/tgtg-python)
- [Published TGTG card implementation](https://github.com/brandonbondig/tgtg_auto/blob/main/tgtgpython/tgtg/__init__.py)
- [TGTG v8 schema](https://pkg.go.dev/github.com/importnil/toogoodtogogo)
- [py-adyen-encrypt](https://github.com/66niko99/py-adyen-encrypt)
