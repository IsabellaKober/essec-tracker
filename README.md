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
| `DASHBOARD_PASSWORD` | The password that decrypts the dashboard (see below) | ✅ already set |

None of these are committed to the repo, so none appear on the public
dashboard. If you ever set a secret yourself from PowerShell, use
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

### Editing from the dashboard

Everything below is optional manual editing on top of the automated flow
above - the dashboard itself is still just static HTML on GitHub Pages, so
each of these buttons publishes a plain-text command to the same ntfy
commands topic the checklist already uses; `process_commands.py` applies it
on the next scheduled or manual workflow run (so changes take up to 3 hours
to show up, same as everything else here):

- **↺ Undo** next to a checklist item you just clicked, or next to a
  course's "Last completed: Session N" line - reverses a `check`/`done`
  back to not-done. Sends `uncheck <course-id> <item-key> <n,n,…>` or
  `undo <course-id>-<n>`.
- **✎ (edit) on a deadline** - opens an inline form to change its name, due
  date, or weight %. Sends `edit-deadline|<id>|<name>|<due_date>|<weight>`,
  applied to the matching entry in `deadlines.yaml`.
- **"→ tomorrow" / "→ the day after" on a suggested task** - pins that
  course's whole suggested backlog to a different one of the three days,
  overriding `build_suggested_plan()`'s automatic placement. Sends
  `move|<course-id>|<today|tomorrow|day_after>`, stored in
  `sessions/.state/day_overrides.yaml` until the course has nothing
  outstanding any more (then it's dropped automatically).

Same manual fallback applies as for `done`/`check`: any of these commands
can also be typed by hand into the commands topic's "Publish message"
screen if the dashboard itself isn't handy.

### 3. GitHub Pages

Already enabled (branch `main`, folder `/docs`). Dashboard:
https://isabellakober.github.io/essec-tracker/

GitHub Pages has no "private site" option outside GitHub Enterprise - a
Pages site is publicly reachable at its URL even when the source repo is
private, on every other plan. So instead of relying on repo visibility,
`docs/data.json` itself is encrypted (AES-256-GCM, key derived via PBKDF2
from `DASHBOARD_PASSWORD`) by `build_dashboard_data.py`, and only decrypted
in the browser via the Web Crypto API after the password is entered on the
lock screen. The page's own HTML/JS stays publicly loadable (it's just
app code, nothing personal), but the real content - deadlines, backlog,
holiday dates - is unreadable without the password.

`build_dashboard_data.py` refuses to write `docs/data.json` at all if
`DASHBOARD_PASSWORD` isn't set, rather than falling back to publishing it
unencrypted. The password itself was generated and given to you directly
(not written anywhere in this repo, including this file) - save it in a
password manager. If you ever need to rotate it: set a new
`DASHBOARD_PASSWORD` secret, then re-run the workflow manually (step 5
below) so `docs/data.json` gets re-encrypted with the new one - every
browser that had the old password cached will need it re-entered.

By default the dashboard remembers the password for the current browser
session only (`sessionStorage` - cleared when you close the tab/browser),
so you'll re-enter it on your next visit. That's deliberate: convenient
enough not to be annoying, without leaving it decryptable indefinitely on a
device that isn't only yours.

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
- **Holidays/breaks**: filled in 2026-09-14 from the school portal's
  academic calendar (Semester 3 and 4 term breaks; see the dated comment in
  `holidays.yaml` for the year-shift reasoning). The Spring
  (S8/IBEA/Exchange) break was left out as a different program track — add
  it the same way if it applies. Each entry's `count_from` (its term start)
  drives the "next break" widget's progress bar; add that field to future
  entries too, or leave it off for just the days-remaining text with no bar.

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

## How the suggested lists are chosen

The dashboard used to show one flat "suggested order" combining every
course's outstanding checklist items at once — unreviewable in one sitting,
since a single session's write-up alone takes ~2h. It's now three lists —
today / tomorrow / the day after — built by `build_suggested_plan()` in
`scripts/build_dashboard_data.py`, which *spreads* the backlog across those
three days instead of dumping it all on today or requiring a literal class
that day to show anything:

- Every course with outstanding checklist items gets a `latest_day` it must
  be handled by: met today or yesterday → today or tomorrow (fresh material,
  1-day slack); a class falls in the 3-day window → the day *before* that
  class (day-0 if the class is later today); no signal either way → free to
  land on whichever of the three days is currently lightest.
- Courses are placed tightest-deadline-first, then heaviest-backlog-first,
  each going into the lightest-loaded day within its allowed range — so the
  three days end up close to even instead of one being empty while another
  has everything.
- `DAILY_HEAVY_CAP` (currently 1, confirmed with the user 2026-09-14) caps
  how many real ~2h write-up sessions (review notes + write a summary +
  practice questions — `_is_heavy()` checks for the `write_summary` checklist
  key) land on any single day, even after spreading. A capped-out course
  spills to the next day with room, or - if all three days in the window are
  already full - just doesn't appear yet; it'll surface once the window
  rolls forward. Quick items (an empty checklist, or Chinese's lighter
  watch/review one) aren't capped, since they take minutes, not hours.
- Each item shows *why* it landed on that day (e.g. "class today", "3
  sessions backing up", "today/tomorrow already had a full write-up
  session").

This relies on `scripts/fetch_schedule.py` writing a `classes_by_date` map
(today + the next two days → which courses meet) to
`sessions/.state/schedule.yaml`, alongside the `next_session` data it already
tracked. Until that's been fetched at least once, every course falls back to
the "no signal" case and is placed purely by load-balancing.

## Repo layout

```
courses.yaml              course + syllabus definitions (edit by hand)
deadlines.yaml            assignments/exams (edit by hand)
holidays.yaml             breaks for the "next break" countdown (edit by hand)
sessions/<course>-<n>.yaml  auto-created/updated by the workflow
sessions/.state/          bookkeeping (processed calendar events, command cursor,
                          last biweekly check-in per course, manual day overrides)
scripts/check_ics.py       step 1-2: detect ended classes, create session files
scripts/process_commands.py  step 4: poll ntfy commands topic, apply done/undo/
                          check/uncheck/edit-deadline/move commands
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
