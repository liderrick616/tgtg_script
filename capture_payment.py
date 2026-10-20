"""Optional mitmproxy metadata diagnostic; never captures payment credentials.

The previous helper dumped authorization headers and payment bodies to disk.
It is no longer used for checkout. Configure cards with main.py setup-payment.
This helper only reports sanitized route names and HTTP status codes.
"""
import re
from mitmproxy import ctx


def payment_route(flow):
    if flow.request.host != "apptoogoodtogo.com":
        return None
    path = flow.request.path.split("?", 1)[0]
    if re.fullmatch(r"/api/order/v[0-9]+/[A-Za-z0-9_-]+/(pay|status)", path):
        return re.sub(r"(/api/order/v[0-9]+/)[^/]+", r"\1<order>", path)
    if re.fullmatch(r"/api/payment/v[0-9]+/[A-Za-z0-9_-]+", path):
        return re.sub(r"(/api/payment/v[0-9]+/)[^/]+", r"\1<payment>", path)
    return None


class TGTGPaymentCapture:
    def request(self, flow):
        route = payment_route(flow)
        if route:
            ctx.log.info(f"TGTG checkout request: {route} (body and headers omitted)")

    def response(self, flow):
        route = payment_route(flow)
        if route and flow.response:
            ctx.log.info(f"TGTG checkout response: {route} HTTP {flow.response.status_code}")


addons = [TGTGPaymentCapture()]
