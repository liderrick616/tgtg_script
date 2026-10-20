# Automatic payment setup

The bot can now submit a card payment immediately after it reserves a bag.
This is an experimental integration with TGTG's unofficial v8 payment endpoint.
It has been tested offline, not with a real purchase. The published payment
protocol may differ from the current flow for your account or country.

## Start

Open Terminal and run:

```bash
cd "/Users/derrick/Desktop/tgtg script"
python3 -m pip install -r requirements.txt
python3 main.py setup-payment
```

Enter your card number and expiry in the hidden local prompts. These details are
saved in macOS Keychain, associated with the email in `config.yaml`. They are not
written to YAML, `.env`, logs, or the script's encrypted login-credentials file.
Do not send card details in chat.

Then start the bot with an explicit order limit and currency. This example allows
one reservation attempt this run, costing at most **15.00 CAD including taxes**:

```bash
python3 main.py run --auto-pay --max-total 15.00 --currency CAD
```

Choose your own limit. You will be prompted for the card's CVV once at startup.
It is kept in memory until the process exits and is never saved in Keychain or a
file. Leave the bot running; supported payments then proceed without another
card prompt. A new process requires entering CVV again.

Your existing target items, quantity, polling windows, and notifications continue
to come from `config.yaml`. `--max-total` is a limit on the **whole order**.
With all-favorites monitoring enabled, the first eligible available favorite can
consume the run's reservation allowance.

## Optional persistent settings

Instead of command-line switches, add this section to `config.yaml`:

```yaml
payment:
  enabled: true
  max_order_total: "15.00"
  currency: "CAD"
  max_orders_per_run: 1
```

Then use `python3 main.py run`. Automatic payment defaults to disabled when the
section is absent. `max_orders_per_run` counts reservation attempts, including
ambiguous failures. Increase it only when you want the bot to attempt more orders;
the maximum potential spend this run is the per-order limit times that allowance.

Automatic payment also requires `reservation.auto_reserve: true`.

## Outcomes and duplicate prevention

- **BAG PURCHASED:** TGTG returned an explicit successful payment state for the
  expected order and payment identifiers.
- **TGTG: CHECK ORDER:** a payment was declined, requires bank verification, has
  an unknown result, or could not be submitted. Open the app and inspect the order
  before paying again. A response with HTTP 200 alone is not treated as success.
- A pending payment is checked up to five times. The payment POST is never retried.
- Final tax-inclusive price, currency, item ID, and quantity are checked before
  sending payment. Missing or unsupported data stops automatic checkout.
- One item/pickup-window reservation attempt is recorded durably, so restarting
  or running both script copies does not automatically buy it again.

The guard database is shared by both script copies at:

`~/Library/Application Support/TGTG Sniper/payment_state.sqlite3`

It stores a hash of your account email, item/pickup identifiers, order identifiers,
and outcomes. It contains no card information. Do not remove it to retry a payment
whose result is uncertain. After a failed or interrupted reservation, use the app
for that pickup window; the next pickup window can be attempted normally.

Bank authentication such as 3-D Secure is not automated. You may need to complete
or restart checkout inside the official app. Saved cards in the TGTG app are not
imported or replayed; each script payment uses freshly encrypted card fields.

## Inspect or remove a saved card

```bash
python3 main.py payment-status
python3 main.py forget-payment
```

`payment-status` displays only the last four digits and local setup status; it
does not validate a charge. `forget-payment` removes Keychain storage. Stop any
running bot as well to clear its in-memory card/CVV references.

## Validation and implementation notes

Run the tests without using your account or card:

```bash
python3 -m pip install pytest
python3 -m pytest -q
```

Tests block network access and use synthetic card data and generated RSA keys.
They cover encryption round trips, amount/currency checks, payment outcomes,
timeouts, redirects, duplicate guards, and the manual-payment fallback.

The TGTG package is pinned to 0.19.0 because the integration reuses its
authenticated headers and cookies. The payment transport sends one request
directly and does not invoke the package's automatic DataDome retry mechanism.

The old `capture_payment.py` helper now emits only sanitized route names and HTTP
status codes. It no longer prints or saves bodies, card data, authorization
headers, or payment tokens. It is not required for the new feature.

Protocol references:

- [tgtg-python](https://github.com/ahivert/tgtg-python): reservations and order totals;
  the base library does not implement payment.
- [Published TGTG card flow](https://github.com/brandonbondig/tgtg_auto/blob/main/tgtgpython/tgtg/__init__.py):
  Adyen card field names and public client-key endpoint.
- [TGTG v8 payment schema](https://pkg.go.dev/github.com/importnil/toogoodtogogo):
  authorization list, final amount, and payment-status schema, published in 2024.
- [py-adyen-encrypt](https://github.com/66niko99/py-adyen-encrypt):
  legacy CSE encoding, adapted with its MIT license.

The public Adyen key endpoint responded on October 20, 2026. That verifies key
retrieval only; it does not establish that TGTG currently accepts this checkout
flow. Live compatibility, card acceptance, and bank approval remain unverified.

## If startup reports HTTP 403 / DataDome

This happens during account/item access, before card payment. The former
“credentials loaded” message meant the local login file was read; it did not
prove that TGTG accepted those credentials. The former error handler also labeled
every HTTP 403 as DataDome, even when the response did not identify that service.

The bot now checks API access before requesting CVV. It stops on HTTP 401/403,
and its API transport does not generate anti-bot fingerprints or automatically
retry denied requests. This handles the failure; it does not remove a block
imposed by TGTG.

1. Stop an already-running copy with Ctrl+C. File updates do not change a process
   that is already running.
2. Open the official TGTG app and check account access there. Complete any
   verification the official app presents. Working app access does not guarantee
   that the script will be allowed.
3. When ready to check again, make one read-only check:

   ```bash
   cd "/Users/derrick/Desktop/tgtg script"
   python3 main.py check-access
   ```

   This reads favorites without reading card details, making a reservation, or
   attempting payment. If it still returns 403, the script cannot operate yet.
   Use the official app and seek help from TGTG for unresolved account/access
   restrictions. A 401 instead indicates the saved login was rejected; use
   `python3 main.py login` to reauthenticate.

After `check-access` succeeds, this runs with normal polling only:

```bash
python3 main.py run --auto-pay --max-total 15.00 --currency CAD --no-burst
```

`--no-burst` applies to that run and leaves your configured windows intact.
Burst-window comparisons now support both `0:00` and `00:00`, as well as windows
that cross midnight. Using long windows with a three-second interval produces
many requests; slower polling does not guarantee that a server block will clear.
The old `polling.error_cooldown` setting no longer causes a retry after a 403.

An upstream report also describes DataDome login failures:
[tgtg-python issue #396](https://github.com/ahivert/tgtg-python/issues/396).
That report establishes a known failure mode, not the precise cause of every 403.
