"""
capture_payment.py — mitmproxy addon script to capture TGTG payment payloads.

Usage:
    mitmproxy -s capture_payment.py -p 8080

This script watches for the TGTG pay endpoint and saves the authorization
payload to payment_token.json for use by the auto-payment module.
"""

import json
import os
from datetime import datetime
from mitmproxy import http, ctx

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "payment_token.json")

# Endpoints we care about
PAY_ENDPOINT = "/api/order/"
PAYMENT_KEYWORDS = ["/pay", "payment", "paymentMethods"]


class TGTGPaymentCapture:
    def __init__(self):
        self.captured = False
        ctx.log.info("🔍 TGTG Payment Capture loaded. Waiting for payment request...")
        ctx.log.info(f"   Output will be saved to: {OUTPUT_FILE}")
        ctx.log.info("   Make a payment in the TGTG app on your phone now!")

    def request(self, flow: http.HTTPFlow):
        """Capture outgoing requests to TGTG payment endpoints."""
        url = flow.request.pretty_url

        # Log all TGTG API requests for debugging
        if "toogoodtogo" in url or "apptoogoodtogo" in url:
            ctx.log.info(f"📡 {flow.request.method} {url}")

            # Check if this is a payment-related request
            if any(kw in url.lower() for kw in PAYMENT_KEYWORDS):
                ctx.log.alert(f"💳 PAYMENT REQUEST DETECTED: {url}")

                # Capture the request body
                if flow.request.content:
                    try:
                        body = json.loads(flow.request.content.decode("utf-8"))
                        ctx.log.alert(f"📦 Request body: {json.dumps(body, indent=2)}")

                        # Save the full request details
                        capture_data = {
                            "captured_at": datetime.now().isoformat(),
                            "url": url,
                            "method": flow.request.method,
                            "headers": dict(flow.request.headers),
                            "body": body,
                        }

                        # If this is the actual pay endpoint, extract the authorization
                        if "/pay" in url and "authorizations" in body:
                            capture_data["authorizations"] = body["authorizations"]
                            self.captured = True
                            ctx.log.alert("🎉 PAYMENT AUTHORIZATION CAPTURED!")

                        self._save(capture_data)
                    except json.JSONDecodeError:
                        ctx.log.info(f"   Raw body: {flow.request.content[:500]}")

    def response(self, flow: http.HTTPFlow):
        """Capture responses from payment endpoints."""
        url = flow.request.pretty_url

        if "toogoodtogo" in url or "apptoogoodtogo" in url:
            if any(kw in url.lower() for kw in PAYMENT_KEYWORDS):
                ctx.log.info(f"📬 Response {flow.response.status_code} for {url}")
                if flow.response.content:
                    try:
                        resp_body = json.loads(flow.response.content.decode("utf-8"))
                        ctx.log.info(f"   Response: {json.dumps(resp_body, indent=2)[:500]}")

                        # Also save responses (might contain payment method IDs)
                        self._save({
                            "type": "response",
                            "captured_at": datetime.now().isoformat(),
                            "url": url,
                            "status": flow.response.status_code,
                            "body": resp_body,
                        }, filename="payment_responses.json")
                    except json.JSONDecodeError:
                        pass

    def _save(self, data: dict, filename: str = None):
        """Save captured data to a JSON file."""
        filepath = os.path.join(SCRIPT_DIR, filename) if filename else OUTPUT_FILE
        
        # Append to existing captures
        existing = []
        if os.path.exists(filepath):
            try:
                with open(filepath, "r") as f:
                    existing = json.load(f)
                    if not isinstance(existing, list):
                        existing = [existing]
            except (json.JSONDecodeError, Exception):
                existing = []

        existing.append(data)

        with open(filepath, "w") as f:
            json.dump(existing, f, indent=2)

        ctx.log.info(f"💾 Saved to {filepath}")


addons = [TGTGPaymentCapture()]
