"""Shared helper so process_commands.py and send_notifications.py can reach
ntfy.sh either directly (local runs, personal networks) or through the
Cloudflare Worker relay (required from GitHub Actions - see
cloudflare-worker/relay.js for why).
"""
import os


def ntfy_base():
    return os.environ.get("NTFY_RELAY_URL", "https://ntfy.sh").rstrip("/")


def ntfy_headers(extra=None):
    headers = {"User-Agent": "essec-tracker/1.0"}
    secret = os.environ.get("NTFY_RELAY_SECRET")
    if secret:
        headers["X-Relay-Secret"] = secret
    if extra:
        headers.update(extra)
    return headers
