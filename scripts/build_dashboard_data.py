"""Aggregate courses.yaml + sessions/*.yaml + deadlines.yaml into
docs/data.json, which the static dashboard (docs/index.html) fetches at
load time. Contains no secrets - safe to publish on GitHub Pages.
"""
import datetime as dt
import json
import os

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COURSES_PATH = os.path.join(ROOT, "courses.yaml")
DEADLINES_PATH = os.path.join(ROOT, "deadlines.yaml")
SESSIONS_DIR = os.path.join(ROOT, "sessions")
SCHEDULE_PATH = os.path.join(SESSIONS_DIR, ".state", "schedule.yaml")
OUT_PATH = os.path.join(ROOT, "docs", "data.json")

# Used for any course that doesn't define its own `checklist:` in
# courses.yaml.
DEFAULT_CHECKLIST = {
    "read_chapter": "Read next chapter",
    "review_notes": "Review today's notes",
    "write_summary": "Write a summary",
    "practice_questions": "Do practice questions",
}

# How many of the real ~2h write-up sessions (review notes + write a summary
# + practice questions) the suggested plan will place on any single day.
# Confirmed with the user 2026-09-14: even after spreading the backlog
# across today/tomorrow/day-after, 3-4 of those landing on one day was still
# unrealistic - 1/day is the real ceiling. Quick items (a course with an
# empty checklist, or Chinese's lighter watch/review checklist) don't count
# against this - they take minutes, not hours.
DAILY_HEAVY_CAP = 1


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_schedule():
    if not os.path.exists(SCHEDULE_PATH):
        return {}, [], {}
    data = load_yaml(SCHEDULE_PATH) or {}
    return data.get("next_session") or {}, data.get("breaks") or [], data.get("classes_by_date") or {}


def _course_items(c):
    return list((c["next_up"] or {}).get("checklist_items") or [])


def _is_heavy(checklist_labels):
    """A course counts as a real ~2h write-up session (and so counts against
    DAILY_HEAVY_CAP) if its checklist includes writing a summary - the
    specific task the 2h estimate is about. Spanish/Communication Skills
    (empty checklist) and Chinese (watch-lessons/review-material checklist)
    don't have this key, so they're exempt - a quick click, not a cap slot.
    """
    return "write_summary" in checklist_labels


def build_suggested_plan(out_courses, pending_by_course, classes_by_date, now, checklist_labels_by_course):
    """Spread every course's outstanding backlog across the next three days
    (today / tomorrow / the day after) instead of dumping it all on today
    while the other two sit empty, or requiring a literal class that day to
    show anything at all - and cap the real write-up work at
    DAILY_HEAVY_CAP/day so a day never ends up with more ~2h sessions than
    are actually doable.

    Each course gets a `latest_day` (0/1/2) it must be handled by:
    - met today or yesterday: fresh material, so today or tomorrow (1).
    - a class falls in the window: must finish the day *before* that class
      (so you walk in caught up) - the day before a day-2 class is day 1,
      the day before a day-1 class is day 0 (today), a day-0 class (later
      today) also means today.
    - no signal either way: no deadline, free to land on whichever of the
      three days is currently lightest.

    Heavy (write-up) courses are placed most-constrained-first into the
    lightest-loaded day that still has a free cap slot within their allowed
    range - falling back to *any* day in the window with a free slot if none
    of the allowed days have room (better a day late than not shown), and
    dropped from this 3-day window entirely only if all three days are
    already full; they'll surface once the window rolls forward. Light
    courses aren't capped and are spread the same way, minus the cap.
    """
    today = now.date()
    yesterday_str = (today - dt.timedelta(days=1)).isoformat()
    today_str = today.isoformat()
    window_dates = [today + dt.timedelta(days=offset) for offset in (0, 1, 2)]

    class_day_by_course = {}
    for offset, d in enumerate(window_dates):
        for e in classes_by_date.get(d.isoformat(), []):
            class_day_by_course.setdefault(e["course_id"], offset)

    entries = []
    for c in out_courses:
        items = _course_items(c)
        if not items:
            continue
        recs = pending_by_course.get(c["id"], [])
        pending_count = len(recs)
        class_today = any(r["class_date"] == today_str for r in recs)
        class_yesterday = any(r["class_date"] == yesterday_str for r in recs)
        upcoming_day = class_day_by_course.get(c["id"])

        reasons = []
        if class_today:
            latest_day = 1
            reasons.append("class today")
        elif class_yesterday:
            latest_day = 1
            reasons.append("class yesterday")
        elif upcoming_day is not None:
            latest_day = max(0, upcoming_day - 1)
            day_label = ("today", "tomorrow", "the day after")[upcoming_day]
            reasons.append(f"class {day_label}" if upcoming_day else "class today")
        else:
            latest_day = 2

        if pending_count >= 2:
            reasons.append(f"{pending_count} sessions backing up")
        if not reasons:
            reasons.append("spreading the workload evenly")

        entries.append(
            {
                "course_id": c["id"],
                "course_name": c["name"],
                "items": items,
                "weight": max(pending_count, 1),
                "latest_day": latest_day,
                "reasons": reasons,
                "heavy": _is_heavy(checklist_labels_by_course.get(c["id"], DEFAULT_CHECKLIST)),
            }
        )

    # Tightest deadline first, then heaviest backlog, so those get first
    # pick of the lightest day before more flexible courses fill it up.
    entries.sort(key=lambda e: (e["latest_day"], -e["weight"]))

    buckets = {0: [], 1: [], 2: []}
    heavy_count = [0, 0, 0]
    light_loads = [0, 0, 0]

    for e in [x for x in entries if x["heavy"]]:
        allowed = [d for d in range(e["latest_day"] + 1) if heavy_count[d] < DAILY_HEAVY_CAP]
        pushed_late = False
        if not allowed:
            allowed = [d for d in range(3) if heavy_count[d] < DAILY_HEAVY_CAP]
            pushed_late = True
        if not allowed:
            continue  # no free slot anywhere in the window - resurfaces once it rolls forward
        day = min(allowed, key=lambda d: (heavy_count[d], d))
        heavy_count[day] += 1
        if pushed_late:
            e["reasons"].append("today/tomorrow already had a full write-up session")
        e["reason"] = ", ".join(e["reasons"])
        buckets[day].append(e)

    for e in [x for x in entries if not x["heavy"]]:
        day = min(range(e["latest_day"] + 1), key=lambda d: (light_loads[d], d))
        light_loads[day] += e["weight"]
        e["reason"] = ", ".join(e["reasons"])
        buckets[day].append(e)

    return buckets


def flatten(scored):
    out = []
    for s in scored:
        for item in s["items"]:
            entry = {"course_id": s["course_id"], "course_name": s["course_name"], **item}
            if s.get("reason"):
                entry["reason"] = s["reason"]
            out.append(entry)
    return out


def load_sessions():
    sessions = {}
    if os.path.isdir(SESSIONS_DIR):
        for fn in sorted(os.listdir(SESSIONS_DIR)):
            if not fn.endswith(".yaml"):
                continue
            data = load_yaml(os.path.join(SESSIONS_DIR, fn))
            if not data:
                continue
            sessions[(data["course"], data["session_number"])] = data
    return sessions


def deadline_color(days_remaining, weight_pct):
    if days_remaining < 0:
        return "red"
    if days_remaining <= 3:
        urgency = 5
    elif days_remaining <= 7:
        urgency = 3
    elif days_remaining <= 14:
        urgency = 2
    elif days_remaining <= 30:
        urgency = 1
    else:
        urgency = 0.5
    score = weight_pct * urgency
    if score >= 60:
        return "red"
    if score >= 20:
        return "yellow"
    return "green"


def build_checklist_items(pending, checklist_labels):
    """Roll all pending sessions' outstanding checklist items into one
    clickable list, tied to the most recent (current) pending session.

    An item still outstanding only in the current session is shown with its
    plain label. One outstanding in the current session *and* one or more
    older ones is annotated ("this class and session 2" / "... and sessions
    2, 3"), since checking it off resolves the whole backlog for that item
    in one click. One outstanding only in older sessions (already done for
    the current class) is annotated with just those session numbers.
    """
    if not pending or not checklist_labels:
        return []

    current_number = pending[-1]["session_number"]
    items = []
    for key, label in checklist_labels.items():
        outstanding_sessions = [
            rec["session_number"] for rec in pending if not rec.get("checklist", {}).get(key, False)
        ]
        if not outstanding_sessions:
            continue

        older = [n for n in outstanding_sessions if n != current_number]
        if current_number in outstanding_sessions:
            if not older:
                display_label = label
            elif len(older) == 1:
                display_label = f"{label} (this class and session {older[0]})"
            else:
                display_label = f"{label} (this class and sessions {', '.join(str(n) for n in older)})"
        elif len(older) == 1:
            display_label = f"{label} (session {older[0]})"
        else:
            display_label = f"{label} (sessions {', '.join(str(n) for n in older)})"

        items.append({"key": key, "label": display_label, "sessions": outstanding_sessions})

    items.sort(key=lambda it: it["sessions"][0])
    return items


def build():
    courses = load_yaml(COURSES_PATH)["courses"]
    deadlines = (load_yaml(DEADLINES_PATH) or {}).get("deadlines") or []
    sessions = load_sessions()
    next_session_by_course, breaks, classes_by_date = load_schedule()
    course_by_id = {c["id"]: c for c in courses}
    ntfy_topic = os.environ.get("NTFY_TOPIC")
    now = dt.datetime.now(dt.timezone.utc)

    out_courses = []
    pending_by_course = {}
    checklist_labels_by_course = {}
    for c in courses:
        checklist_labels = c.get("checklist", DEFAULT_CHECKLIST)
        checklist_labels_by_course[c["id"]] = checklist_labels
        held = 0
        done = 0
        pending = []
        session_rows = []
        for s in c["sessions"]:
            rec = sessions.get((c["id"], s["number"]))
            status = rec["status"] if rec else "not_started"
            if status in ("pending_review", "done"):
                held += 1
            if status == "done":
                done += 1
            row = {"number": s["number"], "chapter": s["chapter"], "status": status}
            if rec:
                row["checklist"] = rec.get("checklist", {})
            session_rows.append(row)
            if status == "pending_review":
                pending.append(rec)

        pending.sort(key=lambda r: r["session_number"])
        pending_by_course[c["id"]] = pending
        next_up = None
        if pending:
            rec = pending[-1]  # most recent pending session = the "current" one
            checklist_items = build_checklist_items(pending, checklist_labels)
            if not checklist_items:
                # Empty checklist course (Spanish, Communication Skills): one
                # synthetic action to mark the backlog done, no items to tick.
                checklist_items = [
                    {
                        "key": "_done",
                        "label": "Mark done" if len(pending) == 1 else f"Mark sessions {', '.join(str(r['session_number']) for r in pending)} done",
                        "sessions": [r["session_number"] for r in pending],
                    }
                ]
            next_up = {
                "session_number": rec["session_number"],
                "chapter": rec["chapter"],
                "checklist_items": checklist_items,
            }

        out_courses.append(
            {
                "id": c["id"],
                "name": c["name"],
                "total_sessions": c["total_sessions"],
                "held_sessions": held,
                "done_sessions": done,
                "pending_count": len(pending),
                "next_up": next_up,
                "next_session": next_session_by_course.get(c["id"]),
                "sessions": session_rows,
            }
        )

    today_date = now.date()
    tomorrow_str = (today_date + dt.timedelta(days=1)).isoformat()
    day_after_str = (today_date + dt.timedelta(days=2)).isoformat()

    plan = build_suggested_plan(out_courses, pending_by_course, classes_by_date, now, checklist_labels_by_course)
    suggested_today = flatten(plan[0])
    suggested_tomorrow = flatten(plan[1])
    suggested_day_after = flatten(plan[2])

    today = dt.date.today()
    out_deadlines = []
    for d in deadlines:
        due = dt.date.fromisoformat(str(d["due_date"]))
        days_remaining = (due - today).days
        weight = float(d.get("weight_pct", 0))
        out_deadlines.append(
            {
                "id": d.get("id"),
                "name": d["name"],
                "course": d.get("course"),
                "course_name": course_by_id.get(d.get("course"), {}).get("name", d.get("course")),
                "due_date": d["due_date"],
                "weight_pct": weight,
                "days_remaining": days_remaining,
                "color": deadline_color(days_remaining, weight),
            }
        )
    out_deadlines.sort(key=lambda d: d["days_remaining"])

    data = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "courses": out_courses,
        "deadlines": out_deadlines,
        "suggested_today": suggested_today,
        "suggested_tomorrow": suggested_tomorrow,
        "suggested_tomorrow_date": tomorrow_str,
        "suggested_day_after": suggested_day_after,
        "suggested_day_after_date": day_after_str,
        "breaks": breaks,
        # Publishing here is a deliberate tradeoff: it lets the dashboard send
        # "done"/"check" commands with one click instead of requiring the
        # ntfy app, at the cost of this (public) page revealing the commands
        # topic name to anyone who finds the URL. Omitted entirely if
        # NTFY_TOPIC isn't configured, so the checklist just isn't clickable.
        "ntfy_commands_url": f"https://ntfy.sh/{ntfy_topic}-commands" if ntfy_topic else None,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    build()
