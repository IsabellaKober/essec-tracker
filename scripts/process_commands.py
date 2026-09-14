"""Poll the ntfy '<topic>-commands' topic for commands and apply them to the
matching session file(s):
  - 'done <course-id>-<n>'                 mark a whole session done
  - 'check <course-id> <item-key> <n,n,…>' tick one checklist item (used by
    the dashboard's clickable checklist - see build_dashboard_data.py)

This is also the no-webhook manual fallback: open the ntfy app, subscribe to
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
# From the dashboard's clickable checklist: "check <course-id> <item-key> <n1,n2,...>"
# One click can cover more than one session number when an item was left
# outstanding across a backlog (see build_dashboard_data.py's rollup).
CHECK_RE = re.compile(r"^\s*check\s+([a-z0-9-]+)\s+([a-z0-9_]+)\s+([\d,\s]+)\s*$", re.IGNORECASE)


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


def mark_item(course_id, number, item_key):
    """Tick a single checklist item for one session (from a dashboard click).

    A session whose checklist is empty (e.g. Spanish, Communication Skills)
    uses the synthetic key "_done" to mean "mark the whole session done" -
    those courses have nothing to tick individually.
    """
    path = os.path.join(SESSIONS_DIR, f"{course_id}-{number}.yaml")
    if not os.path.exists(path):
        print(f"No session file for {course_id}-{number}, ignoring command.")
        return False
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if item_key == "_done":
        data["status"] = "done"
        for k in data.get("checklist", {}):
            data["checklist"][k] = True
    else:
        checklist = data.setdefault("checklist", {})
        if item_key not in checklist:
            print(f"{course_id}-{number} has no checklist item '{item_key}', ignoring.")
            return False
        checklist[item_key] = True
        if checklist and all(checklist.values()):
            data["status"] = "done"

    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    print(f"Checked '{item_key}' on {course_id}-{number} (status={data['status']}).")
    return True


def main():
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC not set, skipping command polling.")
        return

    since = load_cursor()
    url = f"https://ntfy.sh/{topic}-commands/json?poll=1&since={since}"

    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "essec-tracker/1.0"})
    except requests.RequestException as e:
        print(f"ntfy poll failed (network error), will retry next scheduled run: {e}")
        return

    if resp.status_code != 200:
        # Best-effort: a transient ntfy.sh outage or quota hiccup shouldn't
        # fail the whole workflow run. Any command sent meanwhile just gets
        # picked up on the next scheduled run instead (the cursor isn't
        # advanced, so nothing is lost).
        print(f"ntfy poll failed ({resp.status_code}), will retry next scheduled run: {resp.text[:300]!r}")
        return

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

        m = CHECK_RE.match(text)
        if m:
            course_id = m.group(1).strip().lower()
            item_key = m.group(2).strip().lower()
            numbers = [int(n) for n in re.findall(r"\d+", m.group(3))]
            for number in numbers:
                if mark_item(course_id, number, item_key):
                    any_done = True
            continue

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
