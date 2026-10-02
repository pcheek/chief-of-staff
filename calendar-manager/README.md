# calendar-manager

Paul's calendar SOP, run by agents on a schedule. They keep the calendar organized,
detailed and accurate, catch overscheduling before it happens, ask when they're unsure, and
remember the answer.

## How a run works

1. Two **cloud routines** on claude.ai/code fire the run whether or not Paul's Mac is on:
   weekdays at 7:52am and Sundays at 4:52pm, Boston time. Each starts a fresh session on
   the private memory repo `pcheek/calendar-manager-memory`. A desktop scheduled task is
   the fallback. `/calendar-manager:schedule` covers both.
2. The run pulls the memory repo and loads the SOP (`skills/calendar-sop`), the promoted
   rules (`learned.md`) and Paul's newest answers (`guidance.md` in the memory repo). Then
   it dispatches:

   | Agent | Job |
   |---|---|
   | `conflict-scanner` | Overlaps, tight travel, overscheduling, lunch, 6pm dinner, OOO. Writes red `NOTE:` events. |
   | `commute-planner` | 1-hour drive-time blocks (15 minutes off-peak). Moves them and flags childcare. |
   | `travel-planner` | `Travel:` all-day events, exact-time flights, trains and buses, airport transit, landing buffers, Callie invites. |
   | `categorizer` | Color categories, free/busy, title formats, reminders. |
   | `notes-reviewer` | Acts on Paul's notes and holds; closes out its own resolved notes. |
   | `one-on-one-auditor` | 1:1 cadence against the confirmed roster (weekly only). |
   | `invite-reconciler` | Reads only invite emails. Every invite you haven't declined must be on the calendar; a missing one gets a red, busy `NOTE: missing invite` placeholder. |
   | `offered-times-tracker` | Times you, or your scheduler, offered by email get red, busy `HOLD: offered to <name>` blocks until the thread settles. Also flags confirmed times that never reached the calendar, and double offers. |

3. The run ends with a short report in the task's chat: what changed, childcare flags,
   proposals, and numbered questions, each with the default the agents use until Paul
   answers.
   Before replying, the run commits its report and any new questions to the memory repo
   as `run <date> <mode>` and pushes them.
4. Paul replies in that chat ("Q7: red. Q9: skip Fridays"), often hours later. The
   `guidance` skill pulls, saves each answer as a rule, and pushes each one immediately.
   It then applies the rule, and every later run follows it.
5. Monthly, `/calendar-manager:promote-guidance` opens a PR here that moves rules that have
   held for two or more runs into the plugin, for review.

## Cloud routines and the memory repo

Cloud sessions don't install plugins, so the memory repo carries a generated copy of this
plugin in its `.claude/`: the skills, the agents, and the guard hook in
`.claude/settings.json`. `scripts/vendor_to_memory.py` (repo root) produces it. In that
copy the commands are `/calendar-run`, `/calendar-guidance`, `/calendar-promote-guidance`
and `/calendar-schedule`. Re-vendor after every plugin release.

| Piece | Where | Committed? |
|---|---|---|
| `guidance.json`, `guidance.md`, `questions.md`, `runs/` | memory repo | Yes, only through `guidance.py sync` |
| `state/` (guard bookkeeping, including `created_events.json`) | memory repo clone | Never (gitignored, and the guard blocks staging it) |
| Guard config | `CALENDAR_MANAGER_CONFIG_JSON` in the cloud environment, written by the setup script to `CALENDAR_MANAGER_CONFIG` outside the repo | Never |

**Sync rules**
- A run pulls with `git pull --rebase` at the start, and commits and pushes at the end.
- On a rejected push, it rebases and retries.
- `guidance.json` merges through a custom union merge driver, which renumbers question IDs
  that collide, so overlapping daily and weekly runs both land.
- Nothing ever force-pushes. The guard denies `git push --force` and its variants.

**One limit to accept.** Each cloud run starts in a fresh container, and `state/` isn't
committed. So a run can edit an event's time, title or description only when it read that
event and confirmed it solo in that same run. Agent-created events from earlier runs get
the same read-first treatment.

## Writes come from riley@cheek.org

With `calendar_id`, `writer_servers` and `agent_identity` in the config (the cloud default):
- every create and update goes through riley@cheek.org's calendar connector
  (`org-connector-google_calendar`), to `calendarId: "paul@cheek.org"` by explicit id;
- events land on Paul's calendar with **Paul as organizer and Riley as creator**, so it's
  obvious what the agents made versus what Paul made by hand;
- the guard denies writes through any other calendar connector, and any write naming
  `primary` or no calendar (through Riley's connector that would be Riley's own calendar);
- an event whose creator is Riley counts as agent-made, so a run can edit it after reading
  it, even though `state/` doesn't survive between cloud runs.

Paul's Gmail is still read through his own Gmail connector, because the org Gmail
connector is Riley's mailbox.

Setup is one step: share `paul@cheek.org` with `riley@cheek.org` with **Make changes to
events** (not "Make changes and manage sharing").

## Time zones

Paul lives in Boston and is often elsewhere, so every run builds a **location timeline**
before it acts: for each day, the IANA zone he's in. It comes from all-day `Travel: <city>`
events (their `Time zone:` line) and his flights, and defaults to America/New_York.

- Agents never do offset or daylight-saving math themselves. `scripts/tz.py` does it from the
  IANA database, and refuses DST gaps and double hours.
- Time-of-day rules (deep work, lunch, no meetings before 7am or after 9pm) apply in his local
  zone that day.
- Boston-only rules (commute, 6pm family dinner, Friday WFH, in-person 1:1s) switch off
  while he's away.
- Flights carry each end's own offset.
- Reports show local time with Boston in parentheses.

The guard enforces the core of this: a timed event without an explicit UTC offset, or with
a `timeZone` that contradicts its offsets, is refused. Rules and city-to-zone mapping:
`skills/calendar-sop/references/timezones.md`.

## Guardrails (`scripts/guard.py`)

A hook enforces these in every calendar-manager session. That covers:
- any session whose prompt invokes `/calendar-manager:*` or `/calendar-run` and friends;
- any session running inside the memory repo (its `.calendar-manager-memory` marker);
- any of this plugin's agents.

Paul's other sessions are unaffected.

| Allowed | Blocked |
|---|---|
| Create events on Paul's own calendar with no guests | Deleting any event, on any calendar connector |
| Change `colorId` and free/busy on any event, silently | Adding or removing guests, Meet links, rooms, guest permissions |
| Change time, title, description and location on solo events (created by the agents, or read and confirmed guest-free in the last 30 minutes) | Editing anything else on events with guests |
| Invite **only** Callie, to `Flight:`, `Train:` or `Bus:` events, `Drive:` events over 60 minutes, and all-day `Travel:` events, all in the travel color | Callie on commutes, drive time, or drives of an hour or less |
| Gmail drafts | RSVPs and declines, Gmail send, reply and forward, Slack send |
| | Raw Calendar API calls through Bash or WebFetch |
| | Any mention of the guard's state or config paths, keyed off the real resolved paths, not a hardcoded folder name |
| | Writes to the guard's code, or to the memory repo's `.claude/`, `.gitignore` or `.gitattributes` |
| | `git add -f`, staging `state/` or a config file, `git push --force` (any form), deleting remote branches |
| | Timed events without an explicit UTC offset, a `timeZone` that contradicts the offsets, or abbreviations like EST/GMT |
| | **Anything in the past:** creating it, editing it (even its color), or moving an event into it |
| | Updating an event the run hasn't read (get, list or search) in the last 30 minutes |
| | With the cloud config: writes through any connector other than Riley's, or to any calendar but `paul@cheek.org` by explicit id |

A denied call is final. The agent logs a question instead.

Nothing the agents learn can loosen the guard. The guard is code, and it reads only its
config:
- the `CALENDAR_MANAGER_CONFIG_JSON` environment variable, which no commit can change;
- or the config file, which sits outside the repo and which the agents can't touch.

## Files

`guidance.py where` prints the paths. In the cloud they live in the memory repo clone; on
the desktop, in `$CALENDAR_MANAGER_HOME` (default `~/.claude/calendar-manager`).

| File | What |
|---|---|
| config | Your email addresses, owner calendars, Callie's address, the travel colorId. Comes from the cloud environment, or `config.json` on the desktop. Edit it yourself. |
| `guidance.md` / `guidance.json` | Your rules, generated by `scripts/guidance.py`. |
| `questions.md` | Open questions. |
| `runs/` | One report per run. |
| `state/` | Guard state. Off limits to the agents, never committed. |

## First run

In a cloud session on the memory repo (the desktop equivalent is
`/calendar-manager:run daily dry-run`):

```
/calendar-run daily dry-run
```

A dry run leaves the calendar alone, but still commits its report and the seeded questions
to the memory repo.

The first run seeds seven questions where the source SOPs conflict, are out of date, or leave a gap:
- the notes color (red vs. purple)
- the airport transit color
- the current 1:1 roster (the bundled one is MIT-era 2024)
- the current commute
- which calendar identity is yours
- who schedules on your behalf, so their offers get held too
- whether you switch Google Calendar's time zone when you travel

Answer them in the chat.

## Tests

```
python3 -m unittest discover -s calendar-manager/tests
```

To check the guard by hand in a run: ask the run to delete a test event. The hook denies it.
