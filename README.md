# ESSEC Academic Tracker

Automated tracker for 8 ESSEC courses (Business Law, Finance, Cost & Budgets,
International Economics, Marketing Research, Communication Skills, Spanish,
Chinese). A GitHub Actions job runs every 3 hours, with no laptop required:

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

### 4. Real data - mostly done, some gaps left

`courses.yaml` and `deadlines.yaml` are filled in from your actual
syllabuses, lecture slides, and the real ICS feed (session dates matched
against "due at Session N" wording in each syllabus). `calendar_match` is
already confirmed against your feed's real event titles (e.g. "Cost &
Budgets Group A - Jee Huay TAN").

What's still missing, flagged with comments in the files themselves:
- **Marketing Research** sessions 3, 4, 6, 7, 9: no materials were found
  for these, so their `chapter` is still `TODO`.
- **Business Law**: no syllabus PDF exists in your folder yet, only
  Session 1-2 lesson slides — sessions 3-10 topics come from that Session
  1 slide's course outline, best-effort. Its group presentation (50%) and
  final exam (50%) have no known date, so they're not in `deadlines.yaml`
  yet.
- **Final exam dates** for Finance, Cost & Budgets, International
  Economics, and Marketing Research are all "exam period, TBD by admin" in
  every syllabus — add them once ESSEC publishes the schedule.
- **Pecha Kucha presentation** (Sept 21, 8:45am): added to
  `deadlines.yaml`, but it isn't one of the 8 tracked courses (it's your
  Field Experience reflection, not a graded course) and its grading weight
  wasn't found anywhere in your files — the 15% in there is a placeholder,
  confirm and update it.
- **Spanish** sessions (all but Session 5) and **Chinese** sessions (all
  but Session 1): no session-by-session topic list exists in either
  syllabus, only grading policy — fill in `chapter` as the term goes on.
- **Spanish midterm** and **Chinese midterm/final**: mentioned in the
  syllabuses but without a clean single weight_pct or a known date/session
  respectively — see the comments in `deadlines.yaml` for the specifics.

To add anything above once you know it, follow the existing entries'
shape:
```yaml
deadlines:
  - id: cost-budgets-final
    course: cost-budgets
    name: "Cost & Budgets Final Exam"
    due_date: "2026-12-05"
    weight_pct: 50
```
`course` must match a course `id` from `courses.yaml` (or leave it
free-text for something outside the 8 tracked courses, like the Pecha
Kucha entry). Urgency (days remaining) and the red/yellow/green color are
computed automatically on every run — never set those by hand.

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
sessions/.state/          bookkeeping (processed calendar events, command cursor,
                          last biweekly check-in per course)
scripts/check_ics.py       step 1-2: detect ended classes, create session files
scripts/process_commands.py  step 4: poll ntfy commands topic, mark sessions done
scripts/send_deadline_checkins.py  biweekly nudge for courses with an empty checklist
scripts/send_notifications.py  step 3: push pending sessions to ntfy
scripts/build_dashboard_data.py  builds docs/data.json for the dashboard
docs/index.html           the public dashboard (GitHub Pages)
.github/workflows/tracker.yml  the scheduled job, every 3 hours
```

## Per-course post-class checklist

Each course in `courses.yaml` has its own `checklist:` mapping (item key ->
label shown in notifications/dashboard) instead of one generic list - see
the comment above `courses:` in that file for which courses get which
tasks. A course can set `checklist: {}` deliberately (Communication Skills,
Spanish): its sessions still go to `pending_review` so you can mark them
done, there's just nothing to check off.

Communication Skills and Spanish also set `checkin_interval_days: 14`: since
their checklist is empty, nothing else prompts a periodic look at their
deadlines, so `scripts/send_deadline_checkins.py` pushes a reminder every 2
weeks listing that course's `deadlines.yaml` entries (with days
left/overdue) so nothing gets missed. Any course can opt into this by
adding the same field.

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
