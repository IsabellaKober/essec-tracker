"""Poll the ntfy '<topic>-commands' topic for commands and apply them to the
matching session/deadline files, or to the suggested-plan day overrides:
  - 'done <course-id>-<n>'                 mark a whole session done
  - 'undo <course-id>-<n>'                 reverse a whole-session 'done'
  - 'check <course-id> <item-key> <n,n,…>' tick one checklist item (used by
    the dashboard's clickable checklist - see build_dashboard_data.py)
  - 'uncheck <course-id> <item-key> <n,n,…>' reverse a 'check'
  - 'edit-deadline|<id>|<name>|<due_date>|<weight_pct>' update a deadline's
    fields in deadlines.yaml (any field left blank between the pipes is
    left unchanged - used by the dashboard's per-deadline edit form)
  - 'move|<course-id>|<today|tomorrow|day_after>' pin a course's suggested
    backlog to one of the three days, overriding the automatic placement
    build_suggested_plan() would otherwise pick (used by the dashboard's
    "move to..." buttons on suggested tasks)

This is also the no-webhook manual fallback: open the ntfy app, subscribe to
'<topic>-commands' too, and use its "Publish message" screen to send a plain
text message like 'done finance-6'. The next scheduled run picks it up.

Reads:
  NTFY_TOPIC   env var (required) - the base topic; commands are read from
               '<NTFY_TOPIC>-commands'
"""
import datetime as dt
import json
import os
import re

import requests
import yaml
from ruamel.yaml import YAML

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SESSIONS_DIR = os.path.join(ROOT, "sessions")
STATE_DIR = os.path.join(SESSIONS_DIR, ".state")
CURSOR_PATH = os.path.join(STATE_DIR, "command_cursor.txt")
DEADLINES_PATH = os.path.join(ROOT, "deadlines.yaml")
DAY_OVERRIDES_PATH = os.path.join(STATE_DIR, "day_overrides.yaml")
VALID_DAYS = ("today", "tomorrow", "day_after")

DONE_RE = re.compile(r"^\s*done\s+(.+?)-(\d+)\s*$", re.IGNORECASE)
UNDO_RE = re.compile(r"^\s*undo\s+(.+?)-(\d+)\s*$", re.IGNORECASE)
# From the dashboard's clickable checklist: "check <course-id> <item-key> <n1,n2,...>"
# One click can cover more than one session number when an item was left
# outstanding across a backlog (see build_dashboard_data.py's rollup).
CHECK_RE = re.compile(r"^\s*check\s+([a-z0-9-]+)\s+([a-z0-9_]+)\s+([\d,\s]+)\s*$", re.IGNORECASE)
UNCHECK_RE = re.compile(r"^\s*uncheck\s+([a-z0-9-]+)\s+([a-z0-9_]+)\s+([\d,\s]+)\s*$", re.IGNORECASE)
# Pipe-delimited (not space-delimited) since a deadline name has spaces.
# Fields left empty between the pipes ('||') are left unchanged.
EDIT_DEADLINE_RE = re.compile(r"^\s*edit-deadline\|([^|]+)\|([^|]*)\|([^|]*)\|([^|]*)\s*$", re.IGNORECASE)
MOVE_RE = re.compile(r"^\s*move\|([a-z0-9-]+)\|(today|tomorrow|day_after)\s*$", re.IGNORECASE)

_yaml_rt = YAML()
_yaml_rt.preserve_quotes = True


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


def undo_session(course_id, number):
    """Reverse of mark_done - back to pending_review with every checklist
    item unticked, for when a whole session was accidentally marked done.
    """
    path = os.path.join(SESSIONS_DIR, f"{course_id}-{number}.yaml")
    if not os.path.exists(path):
        print(f"No session file for {course_id}-{number}, ignoring command.")
        return False
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data["status"] = "pending_review"
    for k in data.get("checklist", {}):
        data["checklist"][k] = False
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    print(f"Undid {course_id}-{number} (back to pending_review).")
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


def unmark_item(course_id, number, item_key):
    """Reverse of mark_item - unticks the item (and, if it had made the
    whole session 'done', reopens it back to pending_review).
    """
    path = os.path.join(SESSIONS_DIR, f"{course_id}-{number}.yaml")
    if not os.path.exists(path):
        print(f"No session file for {course_id}-{number}, ignoring command.")
        return False
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if item_key == "_done":
        data["status"] = "pending_review"
        for k in data.get("checklist", {}):
            data["checklist"][k] = False
    else:
        checklist = data.setdefault("checklist", {})
        if item_key not in checklist:
            print(f"{course_id}-{number} has no checklist item '{item_key}', ignoring.")
            return False
        checklist[item_key] = False
        data["status"] = "pending_review"

    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    print(f"Unchecked '{item_key}' on {course_id}-{number} (status={data['status']}).")
    return True


def edit_deadline(deadline_id, name, due_date, weight_pct):
    """Update one deadline's fields in place. Uses ruamel.yaml's round-trip
    mode (not the plain pyyaml used elsewhere) because deadlines.yaml is
    hand-annotated with a lot of context comments that a plain
    load-then-dump would silently discard.
    """
    if not os.path.exists(DEADLINES_PATH):
        print("deadlines.yaml not found, ignoring edit-deadline command.")
        return False
    with open(DEADLINES_PATH, encoding="utf-8") as f:
        doc = _yaml_rt.load(f)
    target = None
    for d in doc.get("deadlines") or []:
        if d.get("id") == deadline_id:
            target = d
            break
    if target is None:
        print(f"No deadline with id '{deadline_id}', ignoring.")
        return False

    changed = False
    if name:
        target["name"] = name
        changed = True
    if due_date:
        try:
            dt.date.fromisoformat(due_date)
        except ValueError:
            print(f"Invalid due_date '{due_date}' for {deadline_id}, ignoring that field.")
        else:
            target["due_date"] = due_date
            changed = True
    if weight_pct:
        try:
            value = float(weight_pct)
        except ValueError:
            print(f"Invalid weight_pct '{weight_pct}' for {deadline_id}, ignoring that field.")
        else:
            target["weight_pct"] = int(value) if value.is_integer() else value
            changed = True

    if not changed:
        print(f"edit-deadline for '{deadline_id}' had no valid fields, ignoring.")
        return False

    with open(DEADLINES_PATH, "w", encoding="utf-8") as f:
        _yaml_rt.dump(doc, f)
    print(f"Updated deadline '{deadline_id}'.")
    return True


def load_day_overrides():
    if not os.path.exists(DAY_OVERRIDES_PATH):
        return {}
    with open(DAY_OVERRIDES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_day_overrides(overrides):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(DAY_OVERRIDES_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(overrides, f, sort_keys=True, allow_unicode=True)


def move_course(course_id, day):
    """Pin a course's whole suggested backlog to one of the three days.
    build_suggested_plan() (in build_dashboard_data.py) applies this on the
    next rebuild and prunes it once the course no longer has anything
    outstanding, so a stale override can't linger forever.
    """
    if day not in VALID_DAYS:
        print(f"Unknown day '{day}' for move command, ignoring.")
        return False
    overrides = load_day_overrides()
    overrides[course_id] = day
    save_day_overrides(overrides)
    print(f"Moved '{course_id}' to {day}.")
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

        m = UNCHECK_RE.match(text)
        if m:
            course_id = m.group(1).strip().lower()
            item_key = m.group(2).strip().lower()
            numbers = [int(n) for n in re.findall(r"\d+", m.group(3))]
            for number in numbers:
                if unmark_item(course_id, number, item_key):
                    any_done = True
            continue

        m = EDIT_DEADLINE_RE.match(text)
        if m:
            deadline_id = m.group(1).strip()
            name, due_date, weight_pct = (g.strip() for g in m.groups()[1:])
            if edit_deadline(deadline_id, name, due_date, weight_pct):
                any_done = True
            continue

        m = MOVE_RE.match(text)
        if m:
            course_id = m.group(1).strip().lower()
            day = m.group(2).strip().lower()
            if move_course(course_id, day):
                any_done = True
            continue

        m = UNDO_RE.match(text)
        if m:
            course_id, number = m.group(1).strip().lower(), int(m.group(2))
            if undo_session(course_id, number):
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
