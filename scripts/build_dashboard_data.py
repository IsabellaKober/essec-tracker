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
OUT_PATH = os.path.join(ROOT, "docs", "data.json")

CHECKLIST_LABELS = {
    "read_chapter": "Read next chapter",
    "review_notes": "Review today's notes",
    "write_summary": "Write a summary",
    "practice_questions": "Do practice questions",
}


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


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


def build():
    courses = load_yaml(COURSES_PATH)["courses"]
    deadlines = (load_yaml(DEADLINES_PATH) or {}).get("deadlines") or []
    sessions = load_sessions()
    course_by_id = {c["id"]: c for c in courses}

    out_courses = []
    for c in courses:
        done = 0
        pending = []
        session_rows = []
        for s in c["sessions"]:
            rec = sessions.get((c["id"], s["number"]))
            status = rec["status"] if rec else "not_started"
            if status == "done":
                done += 1
            row = {"number": s["number"], "chapter": s["chapter"], "status": status}
            if rec:
                row["checklist"] = rec.get("checklist", {})
            session_rows.append(row)
            if status == "pending_review":
                pending.append(rec)

        pending.sort(key=lambda r: r["session_number"])
        next_up = None
        if pending:
            rec = pending[0]
            outstanding = [
                CHECKLIST_LABELS[k]
                for k, v in rec.get("checklist", {}).items()
                if not v and k in CHECKLIST_LABELS
            ]
            next_up = {
                "session_number": rec["session_number"],
                "chapter": rec["chapter"],
                "outstanding": outstanding,
            }

        out_courses.append(
            {
                "id": c["id"],
                "name": c["name"],
                "total_sessions": c["total_sessions"],
                "done_sessions": done,
                "pending_count": len(pending),
                "next_up": next_up,
                "sessions": session_rows,
            }
        )

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
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "courses": out_courses,
        "deadlines": out_deadlines,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    build()
