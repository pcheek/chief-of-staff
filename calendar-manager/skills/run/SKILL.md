---
name: run
description: "Scheduled-task entry point for calendar-manager. Invoke as /calendar-manager:run daily, /calendar-manager:run weekly, /calendar-manager:run quarter (a one-off pass over the next 90 days), or add dry-run to report without changing the calendar. Pulls the memory repo, loads Paul's calendar SOP and learned guidance, dispatches the calendar agents (conflict scanner, commute planner, travel planner, categorizer, notes reviewer, and weekly the 1:1 auditor), merges their questions, writes a run report, commits and pushes it to the memory repo, and ends by asking Paul the open questions in this session. When Paul replies, record his answers with the guidance skill so the agents learn."
---

# calendar-manager run

This is the prompt a cloud routine fires (or a desktop scheduled task, as a fallback).
Invoking it, or running inside the memory repo, marks the session as guarded: the hook
then blocks deletes, invites (Callie on travel aside), RSVPs, outbound messages, force
pushes, and any touch of the guard's state or config for the rest of the session.

**Memory.** Everything the agents learn lives in the memory folder: in the cloud, a clone
of the private `pcheek/calendar-manager-memory` repo, pushed straight to its `main` branch
(not a `claude/` branch). `G where` prints the paths. Only `guidance.json`, `guidance.md`,
`questions.md` and `runs/` are ever committed, and only through `G sync`, which rebases and
retries when another run pushed first and never force-pushes.

`G` = `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guidance.py"`

`$ARGUMENTS`: `daily` (the default), `weekly` or `quarter`, optionally with `dry-run`.

**Windows.** Every agent gets the **window**; travel-planner also gets the **travel window**,
because trips are booked months ahead.

| Mode | Window | Travel window |
|---|---|---|
| `daily` | now plus 48 hours | same as the window |
| `weekly` | today through the end of the week after next | today plus 90 days |
| `quarter` | today plus 90 days | today plus 90 days |

`quarter` is the one-off Paul fires by hand (the "Calendar quarter" routine) to set up the
next three months at once. It runs every agent except `one-on-one-auditor` (a weekly
cadence check). Its report can be long: lead with counts per agent.

## Steps

1. **Set up.**
   - `G sync pull`. If it fails, carry on with what's on disk and say so in the report.
   - `G init`. It's idempotent, and on the first run it seeds questions about gaps in the
     SOP. Read any WARNING it prints about config or `.gitignore` into the report.
   - Get the current time: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tz.py" now`.
   - **Write identity.** `G where` shows the config. If it names a `calendar_id`
     (paul@cheek.org), every write goes through riley@cheek.org's calendar connector
     (`mcp__org-connector-google_calendar__*`).
     - Confirm Riley can reach Paul's calendar: `list_events` on `calendarId:
       "paul@cheek.org"` for the next hour. (A shared calendar Riley never subscribed to is
       missing from `list_calendars` but still works, so don't rely on that list.) If the
       read fails, stop and report: "Paul's calendar isn't shared with riley@cheek.org
       (Make changes to events)."
     - Tell every agent: "writes go through riley@cheek.org, calendarId paul@cheek.org".
   - Without a `calendar_id` (desktop), use Paul's Google Calendar connector. If no calendar
     connector is available, stop and say so.
   - Paul's Gmail connector (`mcp__Gmail__*`) is required for invites and offered times.
     Never use the org Gmail connector, which is Riley's mailbox.
2. **Load context.** Read `${CLAUDE_PLUGIN_ROOT}/skills/calendar-sop/SKILL.md`, then
   `guidance.md` and `questions.md` in the memory folder.
3. **Build the location timeline** for the travel window, the longer of the two
   (`references/timezones.md`).
   - List all-day `Travel:` events, Paul's own `Paul in <city>` / `<city> trip` markers, and
     flights, trains and buses covering the window.
   - For each date, record Paul's IANA zone (the `Time zone:` line, or
     `tz.py zone-of "<city>"`; default America/New_York) and the city name.
   - For each trip, record when he lands (plus the landing buffer) and when he leaves for
     the airport, as ISO times with offsets. travel-planner uses them for working location
     and out of office.
   - Note which days have a mid-day zone change (a travel day).
   - Re-read the current time in today's zone (`tz.py now --zone <zone>`). Windows like "the
     next 48 hours" and "today" are measured in that zone.
   - Any city that can't be resolved becomes a question. Treat that day as unknown and skip
     time-of-day rules for it, rather than assuming Boston.
3b. **Apply Paul's decisions** before dispatching agents, so they see the result. The
   Calendar Decisions page (its URL is in guidance.md) keeps every proposal Paul has
   decided. Read its `items` collection with the ArtifactData tool.
   - `approved`: do it as proposed. `revise`: do what `choice.note` says. Both within the
     guardrails, through the same tools and agents as any other change (working locations
     through `scripts/working_location.py`).
   - An item with `ops` (the exact tool inputs) is applied by running `calendar_call.py check`
     on them and passing them unchanged. A revision builds new ones with `calendar_call.py`.
   - A guard denial for a missing UTC offset is a formatting error, not a policy refusal: rebuild
     that call with `calendar_call.py` and send it once more. Every other denial is final.
   - Question items (`kind: "question"`): record the answer with `G answer` (the default
     for `approved`, `choice.note` for `revise`), then `G sync push`.
   - `choice.makeRule`: also record a standing rule with `G add-rule`.
   - Then set the item's `status` to `applied`, or `failed` with `applied.result` saying
     why. Never delete an item or the `log` collection. In a dry run, apply nothing.
4. **Dispatch agents** with the Agent tool. Give each one the mode, the window (see
   **Windows** above), `dry-run` if set, the current date, and the location timeline.
   travel-planner also gets the travel window.
   - **First, in parallel:** `invite-reconciler` and `offered-times-tracker`. Both look at
     14 days of Gmail, whatever the mode.
   - **Then, in parallel:** `conflict-scanner`, `commute-planner`, `travel-planner`,
     `categorizer`, `notes-reviewer`. Weekly runs (not quarter) also get `one-on-one-auditor`. Running
     these second means they see the new placeholders and holds.

   Agents that write the same events run in this order instead: travel-planner, then
   commute-planner, then categorizer. That way colors are applied last.
5. **Merge** each agent's final JSON block. Deduplicate actions and proposals.
6. **Write the report** to `runs/<YYYY-MM-DD>-<mode>-<HHMM>.md` in the memory folder (local
   time; add `-dry-run` for a dry run), with these sections:
   - Changes made (drive-time moves first, each with "check childcare")
   - Missing invites (placeholder created, or not yet accepted, or cancelled but still on
     the calendar)
   - Offered times (new holds, confirmed times not on the calendar, double offers)
   - Proposals for Paul
   - Questions
   - Rules applied
7. **Tick and push.**
   - `G tick` (skip this in a dry run).
   - `G sync push --message "run <YYYY-MM-DD> <mode>"` (for a dry run,
     `"run <YYYY-MM-DD> <mode> dry-run"`). It commits only the memory files, rebases onto
     anything another run pushed meanwhile, and retries.
   - If it still fails, the commit stays local. Say so in the reply, because a cloud
     container is thrown away later.
   - Do this **before** replying. Question IDs can be renumbered when two runs overlap, so
     read them after the push.
7b. **Queue new decisions.** Write each new proposal, missing invite, offered time, travel
   gap, "for you" action and open question to the page's `items` collection (fields:
   `order`, `runId`, `category`, `kind` calendar|you|question, `agent`, `title`, `when` in
   Paul's local time, `proposal`, `why`, `confidence` 0-100, `status: "open"`,
   `choice: null`, `eventIds`, and for calendar changes `ops`: the exact create/update
   inputs, built with `calendar_call.py` so every time carries its offset). Skip any that is
   already open there. Record what this run
   did on its own as `status: "applied"` items, so the page is the full record.
8. **Reply to Paul.** This message is all he sees. Every time in it goes through
   `tz.py show <iso> --local <his zone that day>`, which gives local time with Boston in
   parentheses when he's away. If he's traveling today, open with one line saying where
   he is and the offset from Boston. Keep it short, in this order:
   - One line: what changed, as counts.
   - Childcare flags, if any.
   - Missing invites and offered times not on the calendar, one line each.
   - Proposals, one line each.
   - **Questions**: run `G open`, after the push. Number them with their IDs (`Q7`), each with its
     default in brackets.

     Finish with the Calendar Decisions link: "Decide these there (Do it / Revise / Ignore),
     or reply in this chat (for example 'Q7: red. Q9: skip Fridays') and I'll save it so I
     do it that way from now on."

   If there's nothing to report and no open questions, say so in one line.

## When Paul replies in this session

Use the `guidance` skill: pull, record each answer, push it right away, then act on it.
Replies can come hours later, after this container was recycled, so nothing waits for the
end of the conversation. The session stays guarded, so the same guardrails apply.

## Never

- Create or edit anything that has already started. The guard blocks it, and every update
  needs a read of that event in this run first.

- Run `git` on the memory folder yourself, `git add -f`, or force-push. `G sync` is the only
  way memory gets committed.

- Delete events, invite anyone except Callie on qualifying travel, RSVP, or message anyone.
  The hook enforces this. If a call is denied, the answer is a question, not a workaround.
- Re-ask a question that's already open. `guidance.py ask` deduplicates, and the report
  shows how many times each one has come up.
