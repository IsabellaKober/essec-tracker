"""Poll the ntfy '<topic>-commands' topic for 'done <course-id>-<n>' messages
and mark the matching session file as done.

This is the no-webhook fallback: open the ntfy app, subscribe to
'<topic>-commands' too, and use its "Publish message" screen to send a plain
text message like 'done finance-6'. The next scheduled run picks it up.

Reads:
  NTFY_TOPIC   env var (required) - the base topic; commands are read from
               '<NTFY_TOPIC>-commands'
"""
import json
import os
import re

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS_DIR = os.path.join(ROOT, "sessions")
STATE_DIR = os.path.join(SESSIONS_DIR, ".state")
CURSOR_PATH = os.path.join(STATE_DIR, "command_cursor.txt")

DONE_RE = re.compile(r"^\s*done\s+(.+?)-(\d+)\s*$", re.IGNORECASE)


def load_cursor():
    if os.path.exists(CURSOR_PATH):
        value = open(CURSOR_PATH, encoding="utf-8").read().strip()
        return value or "all"
    return "all"


def save_cursor(value):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(CURSOR_PATH, "w", encoding="utf-8") as f:
        f.write(str(value))


def mark_done(course_id, number):
    path = os.path.join(SESSIONS_DIR, f"{course_id}-{number}.yaml")
    if not os.path.exists(path):
        print(f"No session file for {course_id}-{number}, ignoring command.")
        return False
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["status"] = "done"
    for k in data.get("checklist", {}):
        data["checklist"][k] = True
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    print(f"Marked {course_id}-{number} done.")
    return True


def main():
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC not set, skipping command polling.")
        return

    since = load_cursor()
    url = f"https://ntfy.sh/{topic}-commands/json?poll=1&since={since}"

    resp = requests.get(url, timeout=30, headers={"User-Agent": "essec-tracker/1.0"})
    if resp.status_code != 200:
        print(f"ntfy poll failed: {resp.status_code} {resp.text[:500]!r}")
    resp.raise_for_status()

    last_id = None
    any_done = False
    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if msg.get("event") != "message":
            continue
        last_id = msg.get("id", last_id)
        text = msg.get("message", "")
        m = DONE_RE.match(text)
        if not m:
            print(f"Ignoring unrecognized command: {text!r}")
            continue
        course_id, number = m.group(1).strip().lower(), int(m.group(2))
        if mark_done(course_id, number):
            any_done = True

    if last_id:
        save_cursor(last_id)

    if not any_done:
        print("No new done-commands.")


if __name__ == "__main__":
    main()
