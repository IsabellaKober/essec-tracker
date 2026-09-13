"""Send (or re-send) a push notification via ntfy.sh listing every session
still in pending_review, until each one is marked done. Sends nothing when
there's nothing pending, so this is safe to run every scheduled cycle.

Reads:
  NTFY_TOPIC   env var (required)
"""
import os
import sys

import requests
import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ntfy_base import ntfy_base, ntfy_headers

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS_DIR = os.path.join(ROOT, "sessions")

CHECKLIST_LABELS = {
    "read_chapter": "read chapter",
    "review_notes": "review notes",
    "write_summary": "write summary",
    "practice_questions": "practice Qs",
}


def load_pending():
    pending = []
    if os.path.isdir(SESSIONS_DIR):
        for fn in sorted(os.listdir(SESSIONS_DIR)):
            if not fn.endswith(".yaml"):
                continue
            with open(os.path.join(SESSIONS_DIR, fn), encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if data and data.get("status") == "pending_review":
                pending.append(data)
    pending.sort(key=lambda d: (d["course"], d["session_number"]))
    return pending


def format_line(rec):
    outstanding = [
        CHECKLIST_LABELS[k]
        for k, v in rec.get("checklist", {}).items()
        if not v and k in CHECKLIST_LABELS
    ]
    todo = ", ".join(outstanding) if outstanding else "all steps checked, send done to close it out"
    return f"{rec['course']}-{rec['session_number']} ({rec.get('chapter', '')}): {todo}"


def main():
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC not set, skipping notification.")
        return

    pending = load_pending()
    if not pending:
        print("Nothing pending, no notification sent.")
        return

    body = "\n".join(format_line(r) for r in pending)
    body += (
        "\n\nTo close one out: in the ntfy app, publish 'done <course-id>-<n>' "
        "to the '-commands' topic."
    )

    try:
        resp = requests.post(
            f"{ntfy_base()}/{topic}",
            data=body.encode("utf-8"),
            headers=ntfy_headers({
                "Title": f"ESSEC Tracker: {len(pending)} session(s) to review",
                "Priority": "default",
                "Tags": "books",
            }),
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"ntfy publish failed (network error), will retry next scheduled run: {e}")
        return

    if resp.status_code != 200:
        # Best-effort: ntfy.sh's free tier shares its daily quota across every
        # visitor on the same egress IP (including, via the relay, unrelated
        # Cloudflare Workers traffic), so an occasional failure here is
        # expected. Don't fail the whole workflow run over it - the next
        # scheduled run tries again and the session stays pending either way.
        print(f"ntfy publish failed ({resp.status_code}), will retry next scheduled run: {resp.text[:300]!r}")
        return

    print(f"Sent notification for {len(pending)} pending session(s).")


if __name__ == "__main__":
    main()
