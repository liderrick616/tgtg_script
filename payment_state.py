"""Durable duplicate guards; no payment credentials are stored here."""

import hashlib
import os
from pathlib import Path
import sqlite3


class PaymentState:
    def __init__(self, path, account):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        self.account = hashlib.sha256(account.strip().lower().encode()).hexdigest()
        self.db = sqlite3.connect(path, timeout=5)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS reservations (
            account TEXT, item TEXT, pickup TEXT, order_id TEXT,
            PRIMARY KEY(account, item, pickup))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS payments (
            account TEXT, order_id TEXT, outcome TEXT,
            PRIMARY KEY(account, order_id))""")
        self.db.commit()

    def claim_reservation(self, item_id, pickup):
        with self.db:
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO reservations VALUES (?, ?, ?, NULL)",
                (self.account, item_id, pickup),
            )
        return cursor.rowcount == 1

    def record_reservation(self, item_id, pickup, order_id):
        with self.db:
            self.db.execute(
                "UPDATE reservations SET order_id=? WHERE account=? AND item=? AND pickup=?",
                (order_id, self.account, item_id, pickup),
            )

    def claim_payment(self, order_id):
        # Commit BEFORE sending money. A crash/time-out never permits an automatic replay.
        with self.db:
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO payments VALUES (?, ?, 'submitted')",
                (self.account, order_id),
            )
        return cursor.rowcount == 1

    def record_payment(self, order_id, outcome):
        with self.db:
            self.db.execute(
                "UPDATE payments SET outcome=? WHERE account=? AND order_id=?",
                (outcome, self.account, order_id),
            )

    def close(self):
        self.db.close()
