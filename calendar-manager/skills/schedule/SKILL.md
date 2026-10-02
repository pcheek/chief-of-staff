---
name: schedule
description: "Sets up the Claude scheduled tasks that run calendar-manager. A weekday morning daily run and a Sunday evening weekly lookahead, each firing /calendar-manager:run so the agents work Paul's calendar and ask him questions in that task's session. Use when Paul says schedule, automate, or set up his calendar agents, or wants to change their cadence."
---

# Schedule calendar-manager

## Default cadence (America/New_York)

| Task | Prompt | When |
|---|---|---|
| Calendar daily | `/calendar-manager:run daily` | Weekdays 7:52am, before he leaves home |
| Calendar weekly | `/calendar-manager:run weekly` | Sundays 4:52pm, a three-week lookahead before the week starts |

Times are Boston time (`CRON_TZ=America/New_York` for Routines), so daylight-saving changes
are handled. While Paul travels, the daily run still fires at 7:52am Boston, which can be
the middle of his local day or night. The report always shows his local time. If he wants
the run to follow him instead, he changes the task's time zone; record that as guidance.
Off-hour minutes keep the runs out of the top-of-hour rush. Confirm the times with Paul
before creating anything.

## Where to run it

**Prefer a scheduled task in the Claude desktop app on Paul's own machine.** The learned
guidance lives in `~/.claude/calendar-manager/`, and a local task keeps that folder between
runs. When a run has questions, Paul answers them in that task's conversation.

Setup:
1. Confirm the plugin is installed and enabled there:
   `/plugin marketplace add pcheek/chief-of-staff`, then
   `/plugin install calendar-manager@chief-of-staff`.
2. Confirm the Google Calendar and Gmail connectors are connected.
3. Create two scheduled tasks with the prompts and times above. Use the scheduled-task tool
   if this session has one (CronCreate, or a Routine via create_trigger bound to a
   persistent session). Otherwise give Paul the exact steps for the app's Scheduled tasks
   screen.

**Cloud routines** (claude.ai/code) start in a fresh container each time, which wipes
`~/.claude/calendar-manager`. If Paul wants them anyway, warn him that answers only persist
once promoted to the plugin. Then suggest running `/calendar-manager:promote-guidance`
weekly instead of monthly.

## First run

Do a dry run first, `/calendar-manager:run daily dry-run`, so Paul sees the seeded questions
and the planned changes before anything is written.
