"""Fetch the ESSEC ICS feed, detect classes that have ended, and create a
pending_review session file for each one that doesn't already have one.

Reads:
  ICS_URL          env var (required) - the calendar feed URL
  LOOKBACK_HOURS   env var (optional, default 72) - how far back to look for
                   recently-ended events, so a long gap between runs doesn't
                   cause an old event to be missed once the feed is fetched
                   again (already-processed events are skipped either way).
"""
import datetime as dt
import os

import recurring_ical_events
import requests
import yaml
from icalendar import Calendar

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COURSES_PATH = os.path.join(ROOT, "courses.yaml")
SESSIONS_DIR = os.path.join(ROOT, "sessions")
STATE_DIR = os.path.join(SESSIONS_DIR, ".state")
PROCESSED_EVENTS_PATH = os.path.join(STATE_DIR, "processed_events.yaml")

LOOKBACK_HOURS = int(os.environ.get("LOOKBACK_HOURS", "72"))

# Used for any course that doesn't define its own `checklist:` in
# courses.yaml (e.g. Chinese overrides this with "watch the next 3 lessons").
DEFAULT_CHECKLIST = {
    "read_chapter": "Read next chapter",
    "review_notes": "Review today's notes",
    "write_summary": "Write a summary",
    "practice_questions": "Do practice questions",
}


def load_courses():
    with open(COURSES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["courses"]


def load_processed():
    if not os.path.exists(PROCESSED_EVENTS_PATH):
        return set()
    with open(PROCESSED_EVENTS_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return set(data.get("processed_uids", []))


def save_processed(uids):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PROCESSED_EVENTS_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump({"processed_uids": sorted(uids)}, f)


def match_course(summary, courses):
    s = (summary or "").lower()
    for c in courses:
        for token in c.get("calendar_match", []):
            if token.lower() in s:
                return c
    return None


def next_session_number(course_id, total_sessions):
    existing = []
    if os.path.isdir(SESSIONS_DIR):
        for fn in os.listdir(SESSIONS_DIR):
            if fn.startswith(course_id + "-") and fn.endswith(".yaml"):
                try:
                    existing.append(int(fn[len(course_id) + 1 : -len(".yaml")]))
                except ValueError:
                    continue
    number = max(existing, default=0) + 1
    return None if number > total_sessions else number


def session_file_path(course_id, number):
    return os.path.join(SESSIONS_DIR, f"{course_id}-{number}.yaml")


def create_session(course, number, class_date):
    chapter = "Unknown (add this session to courses.yaml)"
    for s in course["sessions"]:
        if s["number"] == number:
            chapter = s["chapter"]
            break

    checklist_template = course.get("checklist", DEFAULT_CHECKLIST)
    data = {
        "course": course["id"],
        "session_number": number,
        "chapter": chapter,
        "status": "pending_review",
        "class_date": class_date,
        "detected_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checklist": {k: False for k in checklist_template},
        "notes_summary": "",
    }
    path = session_file_path(course["id"], number)
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    return path


def normalize_end(end_dt):
    if isinstance(end_dt, dt.datetime):
        if end_dt.tzinfo is None:
            return end_dt.replace(tzinfo=dt.timezone.utc)
        return end_dt
    # all-day event: treat as ending at midnight UTC that day
    return dt.datetime.combine(end_dt, dt.time.min, tzinfo=dt.timezone.utc)


def main():
    ics_url = os.environ.get("ICS_URL")
    if not ics_url:
        print("ICS_URL not set, skipping calendar check.")
        return

    courses = load_courses()
    processed = load_processed()

    resp = requests.get(ics_url, timeout=30, headers={"User-Agent": "essec-tracker/1.0"})
    resp.raise_for_status()
    cal = Calendar.from_ical(resp.content)

    now = dt.datetime.now(dt.timezone.utc)
    window_start = now - dt.timedelta(hours=LOOKBACK_HOURS)

    raw_events = recurring_ical_events.of(cal).between(window_start, now)

    events = []
    for event in raw_events:
        dtend = event.get("DTEND")
        if dtend is None:
            continue
        end_dt = normalize_end(dtend.dt)
        if end_dt > now:
            continue  # class hasn't ended yet
        events.append((end_dt, event))

    events.sort(key=lambda pair: pair[0])  # chronological, so numbering stays in order

    created = []
    for end_dt, event in events:
        uid = str(event.get("UID", ""))
        summary = str(event.get("SUMMARY", ""))
        course = match_course(summary, courses)
        if course is None:
            continue

        event_key = uid or f"{summary}|{end_dt.isoformat()}"
        if event_key in processed:
            continue

        number = next_session_number(course["id"], course["total_sessions"])
        if number is None:
            print(f"{course['id']}: all {course['total_sessions']} sessions already tracked, skipping '{summary}'")
            processed.add(event_key)
            continue

        path = create_session(course, number, end_dt.date().isoformat())
        processed.add(event_key)
        created.append(path)
        print(f"Created {path} for event '{summary}' (ended {end_dt.isoformat()})")

    save_processed(processed)

    print(f"Created {len(created)} new pending session(s)." if created else "No new ended sessions detected.")


if __name__ == "__main__":
    main()
