# sessions/

This folder is written to automatically by `scripts/check_ics.py` and
`scripts/process_commands.py` — you shouldn't need to hand-edit files here.

Each file is `<course-id>-<session-number>.yaml`, created the first time the
tracker detects (via your ICS calendar feed) that a class for that course has
ended. It starts as `status: pending_review` with an unchecked checklist, and
flips to `status: done` once you send a `done <course-id>-<n>` command (see
main README) or hand-edit the file yourself.

`.state/` (created automatically) holds bookkeeping the scripts need between
runs: which calendar events have already been turned into sessions, and how
far the command-topic poller has read. Don't delete it unless you want the
tracker to reprocess history from scratch.
