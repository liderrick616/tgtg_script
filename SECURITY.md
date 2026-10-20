# Local data and publishing

Keep account and card information out of source control and issue reports.
The included test card values are synthetic fixtures for offline tests.

## Stored data

| Location | Contents |
| --- | --- |
| `config.yaml` | Email, target stores, optional notification credentials |
| `credentials.json` | Encrypted login tokens/cookies |
| `.encryption_key` | Local key that decrypts the login file |
| macOS Keychain service `tgtg-sniper.payment-card.v1` | Card number and expiry, keyed by account email |
| `~/Library/Application Support/TGTG Sniper/payment_state.sqlite3` | Duplicate guards, account hash and order/item metadata |
| Configured log file, if enabled | Operational information including stores and orders |

The login file and its encryption key are on the same machine. Encryption does
not make the login file suitable for publication. Card CVV is kept only in
process memory during a run. File logging is disabled by default.

## Cleanup

1. Stop every running copy of the bot.
2. Run `python3 main.py forget-payment` before erasing the configured email.
   Repeat for each account previously used. Alternatively, delete the entries
   for the exact service above in macOS Keychain Access.
3. Remove `config.yaml`, `credentials.json`, `.encryption_key`, any log/capture
   files, and private backups from each project copy.
4. Remove the payment database and any SQLite sidecar files only when you no
   longer need duplicate protection. Before restarting, inspect existing orders
   in the official app.

Deleting local files does not revoke remote sessions or remove backups and
published copies. If credentials were exposed, revoke/reset the affected
sessions or tokens with the relevant provider.

## Public source

Publish a clean source directory, with `config.example.yaml` and no personal
configuration. Review staged files and Git history as well as the current tree.
`.gitignore` does not untrack previously committed files.

If private data was pushed previously, deleting it in a later commit is
insufficient. Replace or sanitize the remote history and address forks, cached
commit views, releases and other copies separately. GitHub Support can advise
on removal of cached sensitive content.
