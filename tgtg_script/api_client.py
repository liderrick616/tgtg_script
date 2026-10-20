"""Single-request API transport and safe access diagnostics."""

from tgtg import TgtgClient as BaseTgtgClient


class TgtgClient(BaseTgtgClient):
    def _post(self, url, **kwargs):
        # Do not generate device fingerprints or retry a denied request.
        # Reuse only this account's existing authenticated session.
        kwargs.setdefault("allow_redirects", False)
        return self.session.post(
            url, headers=self._headers, proxies=self.proxies,
            timeout=self.timeout, **kwargs,
        )


class APIAccessError(RuntimeError):
    """Safe message that never includes response bodies, tokens or challenge URLs."""


def http_status(error):
    response = getattr(error, "response", None)
    code = getattr(response, "status_code", None)
    if code is None and error.args:
        code = error.args[0]
    if isinstance(code, int) and not isinstance(code, bool) and 100 <= code <= 599:
        return int(code)
    return None


def access_message(error):
    code = http_status(error)
    if code == 403:
        # Inspect only to classify; never print the challenge URL or token.
        content = error.args[1] if len(error.args) > 1 else b""
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        challenge = isinstance(content, str) and any(
            marker in content.lower() for marker in ("datadome", "captcha-delivery.com")
        )
        cause = "a DataDome verification challenge" if challenge else "HTTP 403 (access denied)"
        return (
            f"TGTG returned {cause}. Stopping requests. "
            "Open the official TGTG app and check account access there. "
            "If the app works but the script remains blocked, API access is still unavailable."
        )
    if code == 401:
        return (
            "TGTG rejected the saved login (HTTP 401). "
            "Run 'python3 main.py login' to authenticate again."
        )
    if code == 429:
        return "TGTG rate-limited the request (HTTP 429). Stop the bot and try later."
    if code:
        return f"TGTG API access failed (HTTP {code}). No purchase was attempted."
    return "TGTG API access could not be verified. Check the connection. No purchase was attempted."


def check_access(client):
    """Read favorites once; never reserve, pay, or read stored card information."""
    try:
        items = client.get_items(favorites_only=True)
        if not isinstance(items, list):
            raise APIAccessError("TGTG returned an unexpected item-list format.")
        return items
    except APIAccessError:
        raise
    except Exception as exc:
        raise APIAccessError(access_message(exc)) from None
