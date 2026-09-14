"""Fetch the ESSEC ICS feed to look *ahead* (check_ics.py only looks back,
for classes that already ended): the next scheduled class per course, and
any gaps between back-to-back classes coming up, so the dashboard can show
"Next class: ..." and suggest using free time between classes to catch up
on a subject that just met.

Written to sessions/.state/schedule.yaml, which build_dashboard_data.py
reads (no network access itself) - keeps ICS_URL out of every script
except this one and check_ics.py. Only course ids/names + timestamps are
written; raw calendar text (professor names, room, group labels) never
leaves this script, same discipline as check_ics.py.

Reads:
  ICS_URL                    env var (required)
  NEXT_SESSION_LOOKAHEAD_DAYS env var (optional, default 30)
  BREAK_LOOKAHEAD_HOURS      env var (optional, default 30) - only surface
                             breaks starting within this many hours, so the
                             list stays short and near-term.
  BREAK_MIN_MINUTES          env var (optional, default 20) - shorter gaps
                             are just a passing period, not a real break.
  BREAK_MAX_MINUTES          env var (optional, default 240) - longer gaps
                             aren't "between classes" anymore (e.g. an
                             overnight or multi-day span).
"""
import datetime as dt
import os

import recurring_ical_events
import requests
import yaml
from icalendar import Calendar

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COURSES_PATH = os.path.join(ROOT, "courses.yaml")
STATE_DIR = os.path.join(ROOT, "sessions", ".state")
OUT_PATH = os.path.join(STATE_DIR, "schedule.yaml")

NEXT_SESSION_LOOKAHEAD_DAYS = int(os.environ.get("NEXT_SESSION_LOOKAHEAD_DAYS", "30"))
BREAK_LOOKAHEAD_HOURS = int(os.environ.get("BREAK_LOOKAHEAD_HOURS", "30"))
BREAK_MIN_MINUTES = int(os.environ.get("BREAK_MIN_MINUTES", "20"))
BREAK_MAX_MINUTES = int(os.environ.get("BREAK_MAX_MINUTES", "240"))


def load_courses():
    with open(COURSES_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["courses"]


def match_course(summary, courses):
    s = (summary or "").lower()
    for c in courses:
        for token in c.get("calendar_match", []):
            if token.lower() in s:
                return c
    return None


def normalize(value):
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)
    # all-day entry: treat as starting/ending at midnight UTC that day
    return dt.datetime.combine(value, dt.time.min, tzinfo=dt.timezone.utc)


def class_date(end_dt):
    """Same date derivation check_ics.py uses for a session's class_date
    (attach UTC only if naive, otherwise keep the event's own tzinfo) - kept
    identical on purpose so a date here always matches the class_date a
    pending session file ends up with, letting the dashboard compare them
    directly.
    """
    if end_dt.tzinfo is None:
        return end_dt.replace(tzinfo=dt.timezone.utc).date()
    return end_dt.date()


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    ics_url = os.environ.get("ICS_URL")
    if not ics_url:
        print("ICS_URL not set, skipping schedule fetch.")
        return

    courses = load_courses()
    resp = requests.get(ics_url, timeout=30, headers={"User-Agent": "essec-tracker/1.0"})
    resp.raise_for_status()
    cal = Calendar.from_ical(resp.content)

    now = dt.datetime.now(dt.timezone.utc)
    today = now.date()
    # Reaches back to the start of today (not just 6h) so a class that
    # already happened earlier today still shows up in classes_by_date -
    # needed for the dashboard to know "you had a class today" even hours
    # after it ended.
    window_start = min(now - dt.timedelta(hours=6), dt.datetime.combine(today, dt.time.min, tzinfo=dt.timezone.utc))
    window_end = now + dt.timedelta(days=NEXT_SESSION_LOOKAHEAD_DAYS)

    raw_events = recurring_ical_events.of(cal).between(window_start, window_end)

    matched = []
    for event in raw_events:
        dtstart, dtend = event.get("DTSTART"), event.get("DTEND")
        if dtstart is None or dtend is None:
            continue
        start, end = normalize(dtstart.dt), normalize(dtend.dt)
        if end <= start:
            continue
        course = match_course(str(event.get("SUMMARY", "")), courses)
        if course is None:
            continue
        matched.append(
            {
                "course_id": course["id"],
                "course_name": course["name"],
                "start": start,
                "end": end,
                "class_date": class_date(dtend.dt),
            }
        )

    matched.sort(key=lambda e: e["start"])

    # Today, tomorrow, and the day after - the only three days the dashboard
    # needs a per-day class list for (calendar_match dedup isn't needed here
    # the way check_ics.py needs it: this is just "does this course meet
    # that day", not session bookkeeping).
    relevant_dates = [today + dt.timedelta(days=offset) for offset in (0, 1, 2)]
    classes_by_date = {d.isoformat(): [] for d in relevant_dates}
    for e in matched:
        key = e["class_date"].isoformat()
        if key not in classes_by_date:
            continue
        classes_by_date[key].append(
            {
                "course_id": e["course_id"],
                "course_name": e["course_name"],
                "start": iso(e["start"]),
                "end": iso(e["end"]),
            }
        )

    next_session = {}
    for e in matched:
        if e["end"] < now:
            continue
        next_session.setdefault(e["course_id"], {"start": iso(e["start"]), "end": iso(e["end"])})

    breaks = []
    break_cutoff = now + dt.timedelta(hours=BREAK_LOOKAHEAD_HOURS)
    for prev, nxt in zip(matched, matched[1:]):
        gap_start, gap_end = prev["end"], nxt["start"]
        if gap_end <= now or gap_start > break_cutoff:
            continue
        gap_minutes = (gap_end - gap_start).total_seconds() / 60
        if not (BREAK_MIN_MINUTES <= gap_minutes <= BREAK_MAX_MINUTES):
            continue
        breaks.append(
            {
                "start": iso(gap_start),
                "end": iso(gap_end),
                "after_course_id": prev["course_id"],
                "after_course_name": prev["course_name"],
                "before_course_id": nxt["course_id"],
                "before_course_name": nxt["course_name"],
            }
        )

    os.makedirs(STATE_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            {
                "generated_at": iso(now),
                "next_session": next_session,
                "breaks": breaks,
                "classes_by_date": classes_by_date,
            },
            f,
            sort_keys=False,
        )
    print(
        f"Wrote {OUT_PATH}: {len(next_session)} course(s) with a next class, {len(breaks)} upcoming break(s), "
        f"classes_by_date for {', '.join(classes_by_date)}."
    )


if __name__ == "__main__":
    main()
