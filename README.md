# ESSEC Academic Tracker

Automated tracker for 5 ESSEC courses (Business Law, Finance, Cost & Budgets,
International Economics, Marketing Research). A GitHub Actions job runs every
3 hours, with no laptop required:

1. Fetches your ICS calendar feed and detects classes that have ended.
2. Creates a `pending_review` session entry with a checklist (read next
   chapter, review notes, write summary, practice questions).
3. Sends a push notification via [ntfy.sh](https://ntfy.sh) listing every
   still-pending session, re-sending on every run until you mark it done.
4. Lets you mark a session done with a plain-text command sent from the ntfy
   app — no server or account needed.
5. Rebuilds `docs/data.json`, which the public dashboard
   (`docs/index.html`, served by GitHub Pages) reads.

## One-time setup

### 1. Push this repo to GitHub

```
git init
git add .
git commit -m "Initial tracker scaffold"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

### 2. Add repository secrets

Repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value |
|---|---|
| `ICS_URL` | Your ESSEC calendar's ICS feed URL |
| `NTFY_TOPIC` | Your private ntfy topic (see below) |

Both are secrets, not committed to the repo, so they never appear on the
public dashboard.

### 3. Set up ntfy.sh (no account needed)

1. Install the ntfy app: [iOS](https://apps.apple.com/app/ntfy/id1625396347) /
   [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy).
2. In the app, subscribe to your private topic (treat this string like a
   password — anyone who knows it can read/send on it):
   `essec-tracker-0dabdbd2a4c35b35d502e94b`
3. Also subscribe to the commands topic, used to mark sessions done:
   `essec-tracker-0dabdbd2a4c35b35d502e94b-commands`
4. Set `NTFY_TOPIC` (step 2, above) to `essec-tracker-0dabdbd2a4c35b35d502e94b`
   — the workflow derives the commands topic by appending `-commands` itself.

To mark a session done: in the app, open the commands topic → use "Publish
message" (the pencil/+ icon) → message body `done finance-6` (course id +
session number, from the filename in `sessions/`) → Send. The next scheduled
run (within 3 hours) picks it up and stops re-notifying for it.

### 4. Enable GitHub Pages

Repo → Settings → Pages → Source: "Deploy from a branch" → Branch: `main`,
folder: `/docs`. Your dashboard (and a link you can share as your calendar
link) will be at `https://<you>.github.io/<repo>/`.

### 5. Fill in real data

- **`courses.yaml`**: replace each `TODO: fill in from syllabus` with the
  real chapter/topic for that session, per your syllabus. Adjust
  `calendar_match` if your ICS event titles don't contain the plain course
  name (e.g. if ESSEC labels events "FIN101 - Session 6").
- **`deadlines.yaml`**: add one entry per assignment/exam:
  ```yaml
  deadlines:
    - id: finance-midterm
      course: finance
      name: "Finance Midterm Exam"
      due_date: "2026-10-15"
      weight_pct: 30
  ```
  `course` must match a course `id` from `courses.yaml`. Urgency (days
  remaining) and the red/yellow/green color are computed automatically on
  every run — never set those by hand.

### 6. Run it once manually

Repo → Actions → "Academic Tracker" → "Run workflow", to confirm secrets and
the ICS feed are wired correctly before waiting for the schedule.

## How the deadline color is computed

`scripts/build_dashboard_data.py`, `deadline_color()`:

- Urgency multiplier from days remaining: ≤3d → 5×, ≤7d → 3×, ≤14d → 2×,
  ≤30d → 1×, beyond → 0.5×. Overdue is always red.
- `score = weight_pct × urgency_multiplier`
- `score ≥ 60` → red, `score ≥ 20` → yellow, else green.

This means a 30%-of-grade exam turns red 3 weeks out, while a 5% quiz stays
green until it's almost due — no manual tagging beyond the weight % you
already enter once.

## Repo layout

```
courses.yaml              course + syllabus definitions (edit by hand)
deadlines.yaml            assignments/exams (edit by hand)
sessions/<course>-<n>.yaml  auto-created/updated by the workflow
sessions/.state/          bookkeeping (processed calendar events, command cursor)
scripts/check_ics.py       step 1-2: detect ended classes, create session files
scripts/process_commands.py  step 4: poll ntfy commands topic, mark sessions done
scripts/send_notifications.py  step 3: push pending sessions to ntfy
scripts/build_dashboard_data.py  builds docs/data.json for the dashboard
docs/index.html           the public dashboard (GitHub Pages)
.github/workflows/tracker.yml  the scheduled job, every 3 hours
```

## Notes / limitations

- GitHub Actions `schedule` triggers can be delayed by a few minutes under
  load, and GitHub **disables scheduled workflows automatically after 60
  days of no repo activity** — push a commit (even a trivial one) if you
  come back after a long break and notifications seem to have stopped.
- The "mark done" flow here is the text-command fallback by design (no
  server to run or maintain). If you later want a one-tap "Done" button on
  the notification itself, that needs a small webhook (e.g. a Cloudflare
  Worker with a repo-write token) that ntfy's action buttons can call
  directly — ask to add that on top of this once the fallback feels
  workable in practice.
