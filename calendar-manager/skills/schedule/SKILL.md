---
name: schedule
description: "Sets up the schedules that run calendar-manager: by default two cloud routines on claude.ai/code (a weekday morning daily run and a Sunday evening weekly lookahead) that each start a fresh session on the private memory repo, so they run whether or not Paul's Mac is on. Falls back to Claude desktop scheduled tasks. Use when Paul says schedule, automate, or set up his calendar agents, or wants to change their cadence."
---

# Schedule calendar-manager

## Default cadence (America/New_York)

| Routine | Prompt | When (cron) |
|---|---|---|
| Calendar daily | `/calendar-manager:run daily` | Weekdays 7:52am: `CRON_TZ=America/New_York 52 7 * * 1-5` |
| Calendar weekly | `/calendar-manager:run weekly` | Sundays 4:52pm: `CRON_TZ=America/New_York 52 16 * * 0` |

- **Boston time.** Times are Boston time, so daylight-saving changes are handled.
- **While Paul travels,** the daily run still fires at 7:52am Boston, which can land in the
  middle of his local day or night. The report always shows his local time. If he wants
  the run to follow him instead, change the routine's time and record that as guidance.
- **Off-hour minutes** keep the runs out of the top-of-hour rush.
- **Confirm** the times with Paul before creating anything.

## Default: cloud routines (claude.ai/code/routines)

The cloud runs whether or not Paul's Mac is on. What the agents learn lives in the private
repo `pcheek/calendar-manager-memory`. Every run pulls it at the start, and pushes answers
and reports straight to its `main` branch.

Cloud sessions don't install plugins. Instead, the plugin is copied into the memory repo's
`.claude/` (skills, agents and the guard hook). `scripts/vendor_to_memory.py` in
`pcheek/chief-of-staff` generates that copy. In the cloud, the commands are named
`/calendar-run`, `/calendar-guidance` and so on, because project skills have no plugin
namespace.

Each routine needs:

| Setting | Value |
|---|---|
| Repository | `pcheek/calendar-manager-memory` **only**. With more than one repo, the hook in `.claude/settings.json` doesn't load. |
| Environment | The one with the calendar-manager variables and setup script (below) |
| Connectors | Gmail and Google Calendar only. Remove every other connector. |
| Prompt | `/calendar-run daily` or `/calendar-run weekly` |
| Schedule | The cron above |

Environment variables (in `.env` format, in the environment's settings):

```
CALENDAR_MANAGER_HOME=/home/user/calendar-manager-memory
CALENDAR_MANAGER_CONFIG=/root/.calendar-manager/config.json
CALENDAR_MANAGER_CONFIG_JSON={"owner_emails":["paul@cheek.org","pcheek@mit.edu"],"owner_calendars":["primary"],"callie_email":"calliemcheek@gmail.com","travel_color_ids":["1"],"home_timezone":"America/New_York"}
```

The setup script writes `$CALENDAR_MANAGER_CONFIG` from `$CALENDAR_MANAGER_CONFIG_JSON`,
outside the repo. The guard also reads the variable directly, so an edit to it takes
effect on the next session, even though the setup script's output is cached. If the
memory repo is cloned somewhere else, the guard finds it anyway by its
`.calendar-manager-memory` marker file.

### Creating them

- `/schedule` isn't available inside a cloud session. Create the routines at
  claude.ai/code/routines, or with `create_trigger` when this session has it.
- `create_trigger` can't pick a repository. After creating a routine with it, open the
  routine, choose **Edit**, and add `pcheek/calendar-manager-memory` as its only
  repository, plus the right environment.
- Confirm by running each routine once with **Run now**, then check the run: the hook
  loaded, and a commit landed in the memory repo.

## Fallback: Claude desktop scheduled tasks

If Paul would rather run on his Mac:

1. Install the plugin there:
   - `/plugin marketplace add pcheek/chief-of-staff`
   - `/plugin install calendar-manager@chief-of-staff`
2. Clone `pcheek/calendar-manager-memory` and set `CALENDAR_MANAGER_HOME` to that clone.
   That way desktop and cloud share one memory. Without the variable, memory falls back to
   `~/.claude/calendar-manager`, which isn't synced anywhere.
3. Don't open desktop sessions inside the memory repo with the plugin also enabled: its
   `.claude/` holds the same hook, so it would run twice.
4. Create two scheduled tasks with the prompts and times above (`/calendar-manager:run ...`
   on the desktop).
5. Never run desktop and cloud schedules at the same time. Turn off one set before turning
   on the other.

## First run

Do a dry run first, `/calendar-run daily dry-run` in a cloud session on the memory repo,
so Paul sees the seeded questions and the planned changes before anything touches the
calendar. A dry run still commits its report and questions to the memory repo.
