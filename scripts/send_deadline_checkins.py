"""Send a periodic ntfy reminder for courses that don't get a natural
per-session nudge (their post-class checklist in courses.yaml is empty), so
their upcoming deadlines don't get overlooked.

Runs every scheduled cycle but only actually sends a course's check-in once
`checkin_interval_days` (set per course in courses.yaml) has elapsed since
its last check-in - tracked in sessions/.state/checkins.yaml.

Reads:
  NTFY_TOPIC   env var (required)
"""
import datetime as dt
import os

import requests
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COURSES_PATH = os.path.join(ROOT, "courses.yaml")
DEADLINES_PATH = os.path.join(ROOT, "deadlines.yaml")
STATE_DIR = os.path.join(ROOT, "sessions", ".state")
CHECKINS_PATH = os.path.join(STATE_DIR, "checkins.yaml")


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_last_checkins():
    if not os.path.exists(CHECKINS_PATH):
        return {}
    return load_yaml(CHECKINS_PATH) or {}


def save_last_checkins(data):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(CHECKINS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def due_for_checkin(course, last_checkins, today):
    interval = course.get("checkin_interval_days")
    if not interval:
        return False
    last = last_checkins.get(course["id"])
    if not last:
        return True
    return (today - dt.date.fromisoformat(last)).days >= interval


def format_course_deadlines(course, deadlines, today):
    upcoming = sorted(
        (d for d in deadlines if d.get("course") == course["id"]),
        key=lambda d: d["due_date"],
    )
    if not upcoming:
        return f"{course['name']}: no deadlines on file - add any you know of to deadlines.yaml."
    lines = [f"{course['name']} deadlines:"]
    for d in upcoming:
        due = dt.date.fromisoformat(str(d["due_date"]))
        days = (due - today).days
        when = f"{abs(days)}d overdue" if days < 0 else f"{days}d left"
        lines.append(f"  - {d['name']} ({d.get('weight_pct', '?')}%) due {d['due_date']} - {when}")
    return "\n".join(lines)


def main():
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC not set, skipping deadline check-ins.")
        return

    courses = load_yaml(COURSES_PATH)["courses"]
    deadlines = (load_yaml(DEADLINES_PATH) or {}).get("deadlines") or []
    last_checkins = load_last_checkins()
    today = dt.date.today()

    due_courses = [c for c in courses if due_for_checkin(c, last_checkins, today)]
    if not due_courses:
        print("No course check-ins due.")
        return

    body = "\n\n".join(format_course_deadlines(c, deadlines, today) for c in due_courses)
    body += "\n\nScheduled check-in: review these so nothing slips through unnoticed."

    try:
        resp = requests.post(
            f"https://ntfy.sh/{topic}",
            data=body.encode("utf-8"),
            headers={
                "Title": "Deadline check-in: " + ", ".join(c["name"] for c in due_courses),
                "Priority": "default",
                "Tags": "calendar",
                "User-Agent": "essec-tracker/1.0",
            },
            timeout=30,
        )
    except requests.RequestException as e:
        print(f"ntfy publish failed (network error), will retry next scheduled run: {e}")
        return

    if resp.status_code != 200:
        # Best-effort, same as the other notification scripts: don't fail
        # the whole workflow run over a transient ntfy.sh hiccup. Since
        # last_checkins isn't updated below on this path, the check-in
        # stays due and gets retried next scheduled run.
        print(f"ntfy publish failed ({resp.status_code}), will retry next scheduled run: {resp.text[:300]!r}")
        return

    for c in due_courses:
        last_checkins[c["id"]] = today.isoformat()
    save_last_checkins(last_checkins)
    print(f"Sent check-in for: {', '.join(c['id'] for c in due_courses)}")


if __name__ == "__main__":
    main()
