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


def build_suggested_today(out_courses, pending_by_course, classes_by_date, next_session_by_course, now):
    """Score each course for *today's* list instead of dumping every
    course's backlog into one flat queue (that queue used to list all 8
    courses at once, which is unreviewable in a single sitting when each
    session's write-up takes ~2h on its own).

    A course only shows up here if something makes today the right day for
    it: it met today or yesterday (material's still fresh), its backlog is
    growing (2+ un-reviewed sessions), or its next class is in the next two
    days (clear the backlog before it meets again). No signal -> not on
    today's list, even if it has outstanding items - it'll surface on a day
    that actually calls for it.
    """
    today = now.date()
    yesterday_str = (today - dt.timedelta(days=1)).isoformat()
    today_str = today.isoformat()
    soon_course_ids = {
        e["course_id"]
        for offset in (1, 2)
        for e in classes_by_date.get((today + dt.timedelta(days=offset)).isoformat(), [])
    }

    scored = []
    for c in out_courses:
        items = _course_items(c)
        if not items:
            continue
        recs = pending_by_course.get(c["id"], [])
        pending_count = len(recs)
        class_today = any(r["class_date"] == today_str for r in recs)
        class_yesterday = any(r["class_date"] == yesterday_str for r in recs)

        score = 0
        reasons = []
        if class_today:
            score += 100
            reasons.append("class today")
        elif class_yesterday:
            score += 70
            reasons.append("class yesterday")
        if pending_count >= 2:
            score += 15 * (pending_count - 1)
            reasons.append(f"{pending_count} sessions backing up")
        if c["id"] in soon_course_ids and pending_count >= 1:
            score += 25
            reasons.append("next class coming up")

        if score:
            scored.append({"course_id": c["id"], "course_name": c["name"], "reason": ", ".join(reasons), "items": items, "score": score})

    if not scored:
        # A quiet day: no course met recently, nothing's backing up, nothing
        # meets soon. Still surface the single nearest-urgency course with
        # outstanding items, so the list is never mysteriously empty while
        # work remains - but only that one, not everything at once.
        candidates = [c for c in out_courses if _course_items(c)]
        if candidates:
            def urgency(c):
                next_start = next_session_by_course.get(c["id"], {}).get("start")
                if not next_start:
                    return (1, 0)
                return (0, dt.datetime.strptime(next_start, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc))

            nearest = min(candidates, key=urgency)
            scored.append({"course_id": nearest["id"], "course_name": nearest["name"], "reason": "next up", "items": _course_items(nearest), "score": 1})

    scored.sort(key=lambda s: -s["score"])
    return scored


def build_suggested_for_date(out_courses, date_str, classes_by_date):
    """Courses meeting on `date_str` that still have outstanding checklist
    items from an earlier session - a heads-up to clear the backlog before
    walking into that class, not a full study plan.
    """
    meeting_ids = {e["course_id"] for e in classes_by_date.get(date_str, [])}
    suggested = []
    for c in out_courses:
        if c["id"] not in meeting_ids:
            continue
        items = _course_items(c)
        if not items:
            continue
        suggested.append({"course_id": c["id"], "course_name": c["name"], "items": items})
    return suggested


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
    for c in courses:
        checklist_labels = c.get("checklist", DEFAULT_CHECKLIST)
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

    suggested_today = flatten(build_suggested_today(out_courses, pending_by_course, classes_by_date, next_session_by_course, now))
    suggested_tomorrow = flatten(build_suggested_for_date(out_courses, tomorrow_str, classes_by_date))
    suggested_day_after = flatten(build_suggested_for_date(out_courses, day_after_str, classes_by_date))

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
