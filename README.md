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
   app — no account needed on your phone or in this pipeline.
5. Rebuilds `docs/data.json`, which the public dashboard
   (`docs/index.html`, served by GitHub Pages) reads.

Live repo: https://github.com/IsabellaKober/essec-tracker
Live dashboard: https://isabellakober.github.io/essec-tracker/

Everything below has been tested end-to-end against the real repo, including
manual GitHub Actions runs that actually reached ntfy.sh and rebuilt the
dashboard. (One dead end along the way, in case it's useful history: I first
suspected ntfy.sh was blocking GitHub Actions' IP ranges outright, based on a
string of 404s. It turned out to be a self-inflicted bug — piping a value
into `gh secret set` via PowerShell silently prepends a UTF-8 BOM character,
which corrupted the `NTFY_TOPIC` secret into requesting a different, garbled
topic name. Once the secret was re-set with `gh secret set --body "..."`
instead, direct calls from GitHub Actions to ntfy.sh worked fine — no relay
needed.)

## One-time setup

### 1. Repo, secrets

This repo is already created and pushed, and `NTFY_TOPIC` is already set
correctly. What's left is your two pieces of real data:

Repo → Settings → Secrets and variables → Actions:

| Secret | Value | Status |
|---|---|---|
| `NTFY_TOPIC` | Your private ntfy topic (see below) | ✅ already set |
| `ICS_URL` | Your ESSEC calendar's ICS feed URL | ⬜ needs your real feed |

Neither is committed to the repo, so neither appears on the public dashboard.
If you ever set a secret yourself from PowerShell, use
`gh secret set NAME --body "value"` rather than piping a string in — piping
(`"value" | gh secret set NAME`) adds an invisible BOM character that
corrupts the value (see above).

### 2. Set up ntfy.sh (no account needed)

1. Install the ntfy app: [iOS](https://apps.apple.com/app/ntfy/id1625396347) /
   [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy).
2. In the app, subscribe to your private topic (treat this string like a
   password — anyone who knows it can read/send on it):
   `essec-tracker-0dabdbd2a4c35b35d502e94b`
3. Also subscribe to the commands topic, used to mark sessions done:
   `essec-tracker-0dabdbd2a4c35b35d502e94b-commands`

To mark a session done: in the app, open the commands topic → use "Publish
message" (the pencil/+ icon) → message body `done finance-6` (course id +
session number, from the filename in `sessions/`) → Send. The next scheduled
run (within 3 hours) picks it up and stops re-notifying for it.

### 3. GitHub Pages

Already enabled (branch `main`, folder `/docs`). Dashboard:
https://isabellakober.github.io/essec-tracker/

### 4. Fill in real data

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

### 5. Run it once manually

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
- `process_commands.py` and `send_notifications.py` treat ntfy.sh failures as
  best-effort: a network error or non-200 response is logged and the step
  exits cleanly rather than failing the whole workflow run. A pending session
  just gets re-notified (or a "done" command re-read) on the next scheduled
  run either way, so nothing is lost.
- The "mark done" flow here is the text-command fallback by design (no
  GitHub write-token to manage). If you later want a one-tap "Done" button on
  the notification itself, that needs a small webhook (e.g. a Cloudflare
  Worker with a repo-write token) that ntfy's action buttons can call
  directly — ask to add that on top of this once the fallback feels workable
  in practice.
