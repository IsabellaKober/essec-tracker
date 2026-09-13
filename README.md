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
   app — no account needed on your phone.
5. Rebuilds `docs/data.json`, which the public dashboard
   (`docs/index.html`, served by GitHub Pages) reads.

Live repo: https://github.com/IsabellaKober/essec-tracker
Live dashboard: https://isabellakober.github.io/essec-tracker/

**Important finding from testing:** ntfy.sh blocks GitHub Actions' shared IP
ranges (every request — GET, POST, even plain `curl` — came back 404 from two
different Actions runner IPs, while the exact same request worked fine from a
personal machine). So the workflow can't call ntfy.sh directly; it goes
through a small Cloudflare Worker (`cloudflare-worker/relay.js`) that forwards
the request from Cloudflare's network instead. This only affects how the
*scheduled job* reaches ntfy — your phone still just uses the plain ntfy app
against the plain topic, nothing changes there.

## One-time setup

### 1. Repo, secrets already partly done

This repo is already created and pushed, and the `NTFY_TOPIC` secret is
already set. What's left: deploy the Cloudflare Worker relay (step 2) and add
its two secrets, then add `ICS_URL` once you have the real feed link, then
fill in real syllabus/deadline data (step 5).

Repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value | Status |
|---|---|---|
| `NTFY_TOPIC` | Your private ntfy topic (see below) | ✅ already set |
| `NTFY_RELAY_URL` | Your Cloudflare Worker's `*.workers.dev` URL | ⬜ needs step 2 |
| `NTFY_RELAY_SECRET` | Shared secret the Worker checks for | ⬜ needs step 2 |
| `ICS_URL` | Your ESSEC calendar's ICS feed URL | ⬜ needs your real feed |

All of these are secrets, not committed to the repo, so none of them appear
on the public dashboard.

### 2. Deploy the Cloudflare Worker relay

1. Create a free Cloudflare account at https://dash.cloudflare.com/sign-up
   (no credit card needed for Workers' free tier).
2. Workers & Pages → Create → "Create Worker" → give it any name (e.g.
   `essec-ntfy-relay`) → Deploy the default hello-world first, then click
   "Edit code" and replace the whole file with the contents of
   `cloudflare-worker/relay.js` from this repo → Save and Deploy.
3. In the Worker's Settings → Variables and Secrets → add a secret named
   `RELAY_SECRET` with this value (already generated for you, treat it like a
   password): `6da033ddf9dd12ab7d395ddb06e35560`
4. Copy the Worker's URL (shown at the top of its page, looks like
   `https://essec-ntfy-relay.<your-subdomain>.workers.dev`).
5. Add it as the `NTFY_RELAY_URL` secret in this repo, and add
   `6da033ddf9dd12ab7d395ddb06e35560` as the `NTFY_RELAY_SECRET` secret
   (step 1's table).

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

### 4. GitHub Pages

Already enabled (branch `main`, folder `/docs`). Dashboard:
https://isabellakober.github.io/essec-tracker/

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
scripts/ntfy_base.py       shared helper: talk to ntfy.sh directly, or via the relay
cloudflare-worker/relay.js  the Worker that lets Actions reach ntfy.sh (see above)
docs/index.html           the public dashboard (GitHub Pages)
.github/workflows/tracker.yml  the scheduled job, every 3 hours
```

## Notes / limitations

- GitHub Actions `schedule` triggers can be delayed by a few minutes under
  load, and GitHub **disables scheduled workflows automatically after 60
  days of no repo activity** — push a commit (even a trivial one) if you
  come back after a long break and notifications seem to have stopped.
- ntfy.sh blocks GitHub Actions' IP ranges directly (see top of this file) —
  that's why the Cloudflare Worker relay exists. `scripts/ntfy_base.py` falls
  back to calling ntfy.sh directly whenever `NTFY_RELAY_URL` isn't set, which
  is why local testing (from a personal network) worked without the relay.
- The "mark done" flow here is the text-command fallback by design (no
  GitHub write-token to manage). If you later want a one-tap "Done" button on
  the notification itself, ntfy's action buttons can call the same Cloudflare
  Worker directly — ask to add a `/done` route to `relay.js` that writes back
  to the repo via the GitHub API, once the fallback feels workable in
  practice.
