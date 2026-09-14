"""Send (or re-send) a push notification via ntfy.sh listing every session
still in pending_review, until each one is marked done. Sends nothing when
there's nothing pending, so this is safe to run every scheduled cycle.

Reads:
  NTFY_TOPIC   env var (required)
"""
import os

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS_DIR = os.path.join(ROOT, "sessions")
COURSES_PATH = os.path.join(ROOT, "courses.yaml")

# Used for any course that doesn't define its own `checklist:` in
# courses.yaml.
DEFAULT_CHECKLIST = {
    "read_chapter": "read chapter",
    "review_notes": "review notes",
    "write_summary": "write summary",
    "practice_questions": "practice Qs",
}


def load_checklist_labels():
    with open(COURSES_PATH, encoding="utf-8") as f:
        courses = yaml.safe_load(f)["courses"]
    return {c["id"]: c.get("checklist", DEFAULT_CHECKLIST) for c in courses}


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


def format_line(rec, checklist_labels):
    labels = checklist_labels.get(rec["course"], DEFAULT_CHECKLIST)
    outstanding = [
        labels[k]
        for k, v in rec.get("checklist", {}).items()
        if not v and k in labels
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

    checklist_labels = load_checklist_labels()
    body = "\n".join(format_line(r, checklist_labels) for r in pending)
    body += (
        "\n\nTo close one out: in the ntfy app, publish 'done <course-id>-<n>' "
        "to the '-commands' topic."
    )

    try:
        resp = requests.post(
            f"https://ntfy.sh/{topic}",
            data=body.encode("utf-8"),
            headers={
                "Title": f"ESSEC Tracker: {len(pending)} session(s) to review",
                "Priority": "default",
                "Tags": "books",
                "User-Agent": "essec-tracker/1.0",
            },
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"ntfy publish failed (network error), will retry next scheduled run: {e}")
        return

    if resp.status_code != 200:
        # Best-effort: don't fail the whole workflow run over a transient
        # ntfy.sh hiccup - the next scheduled run tries again and the
        # session stays pending either way.
        print(f"ntfy publish failed ({resp.status_code}), will retry next scheduled run: {resp.text[:300]!r}")
        return

    print(f"Sent notification for {len(pending)} pending session(s).")


if __name__ == "__main__":
    main()
