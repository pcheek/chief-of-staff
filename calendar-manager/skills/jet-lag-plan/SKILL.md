---
name: jet-lag-plan
description: Builds Paul Cheek's jet lag plan for an international flight, including layovers, and writes it to his Google Calendar as gray free FYI blocks titled "Jet Lag - Sleep 😴" and "Jet Lag - Awake ☀️", with the light, caffeine, melatonin and meal instructions in each block's description. Plans only the travel itself: flights and layovers, with no pre-trip schedule shift and nothing after landing. Use whenever a new international flight or a time zone change of 2 hours or more appears on his calendar, or when he asks for a jet lag plan, how to beat jet lag, or how to sleep on a flight.
---

# Jet lag plan

Paul must land fresh and adjusted. The plan covers the flights and layovers only: no pre-trip
schedule shift, and no blocks after landing. The circadian math is in `scripts/jetlag_plan.py`. Your job
is to find the trip, set the inputs, run the script, and turn its `events[]` into calendar
blocks with instructions he can follow from his phone in an airport.

Hard constraints, already built into the script: he can't fall asleep until 30 minutes after
takeoff, he must be up 45 minutes before landing, and he sleeps in a terminal only on a
layover of 6 hours or more.

Copy this checklist and track it:

```
Jet lag plan progress:
- [ ] 1. Find the trip and its legs
- [ ] 2. Skip trips already planned
- [ ] 3. Set the body clock zone
- [ ] 4. Run the script
- [ ] 5. Scan the arrival day
- [ ] 6. Write the calendar blocks
- [ ] 7. Report
```

## 1. Find the trip and its legs

A flight is international when its departure and arrival zones differ by 2 hours or more at
those dates. `scripts/tz.py` does the offset math; never do it by hand. One trip is a chain
of legs where each departs less than 24 hours after the previous lands.

- Start from Paul's calendar for the next 90 days: `Flight:` events, `Travel: <city>`
  events and `Your Itinerary:` events. Read each event's description, because the event's
  own start time is sometimes stored in the wrong zone.
- Confirm every leg against the airline email (`Gmail:search_threads`). Paul's inbox only,
  never Riley's.
- Every leg needs local departure and arrival times plus an IANA zone for each airport
  (`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/tz.py zone-of "<city>"`; ask Paul if a city isn't listed).
  Never derive a leg time from a duration or a layover length.
- When the calendar and the email disagree, use the email and name the difference in the
  report. A leg with no time anywhere: plan the legs you have and ask for the rest.

## 2. Skip trips already planned

Search the trip's window for events whose description contains `Created by jet-lag-plan:
<trip key>`. The trip key is `<first departure date>-<FROM>-<final TO>`, for example
`2026-11-02-BOS-SIN`.

- Found, and no leg changed: report "already planned" and stop.
- Found, and a leg time changed: rerun the plan. Update each existing block that hasn't
  started with `update_event` (same context, new times and description). A block with no
  counterpart in the new plan is retitled `DONE: <title>` and set free. Never delete.

## 3. Set the body clock zone

Read the calendar for the 10 days before departure (`Paul in <city>`, `Travel: <city>`, the
inbound flight). Count nights slept in the departure city.

| Nights in the departure city | `body_tz` |
|---|---|
| 4 or more | the departure city's zone |
| 3 or fewer | the zone he was in before (usually `America/New_York`) |

**Short round trip out of Boston, 3 or fewer nights away:** he stays on Boston time. Set
`dest_tz` to `America/New_York` in step 4. The script then plans in-flight sleep only, against
Boston night. Skip step 5.

`wake` and `bed` default to `06:30` and `22:30`, his Boston weekday rhythm, read as the same
wall clock everywhere. Use his numbers if he gives others.

## 4. Run the script

Write `trip.json` in the scratchpad (format in the script's docstring), then run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jet-lag-plan/scripts/jetlag_plan.py" trip.json
```

It exits 2 with a message on bad input: fix the input and rerun. Never hand-compute offsets,
body times or the shift direction; DST and the 12-hour wrap are where hand math goes wrong.

| Field | Meaning |
|---|---|
| `mode`, `need_h`, `est_days` | `delay` (push later) or `advance` (pull earlier), hours to move, days to full adjustment. `none` = under 2h |
| `residual_shift_at_landing_h`, `body_clock_at_landing` | How adjusted he will be on the ramp, and what his body thinks the time is |
| `warnings` | Short or impossible in-flight sleep, landing in his body night. Quote them to Paul |
| `first_flight_body_night_awake_h` | 3 or more means a departure-day nap (step 6) |
| `events[]` | The blocks to write, flights and layovers only. `kind`, `zone`, `start`, `end` (local wall time), `context`, `light`, `body_from`/`body_to`, and for sleep: `caffeine_cutoff`, `melatonin`, `sleep_hours` |
| `days[0]` | Arrival day, for the report only: `low_window_dest` (circadian low, plus or minus 90 minutes) and `low_point_in_waking_hours` |

Never promise more than the script says. If `residual_shift_at_landing_h` is above 1, tell
Paul plainly he lands partly shifted, and what the plan does about it.

## 5. Scan the arrival day

`Google_Calendar:list_events` for the arrival day and the day after. Flag:

- Any event overlapping `days[0].low_window_dest` when `low_point_in_waking_hours` is true.
  Drives and `Commute` events first (recommend a car service), then teaching, keynotes and
  high-stakes calls.
- A pickup within 30 minutes of an international landing (immigration and bags).
- Paul driving himself on arrival day after a leg he stayed awake through.

Flag only, in the report. Never move, decline or message anyone about an event, and write
nothing to the calendar for these days.

## 6. Write the calendar blocks

Create one block per `events[]` entry that has not started. Never create a block for any time
before takeoff or after landing. Skip any with `end_utc` in the
past (`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/tz.py now`).

Every block, no exceptions:

| Field | Value |
|---|---|
| Title | the script's `title`, exactly: `Jet Lag - Sleep 😴` or `Jet Lag - Awake ☀️` |
| Color | Graphite, `colorId` 8: gray |
| Free/busy | free: these are FYI, not Do Not Schedule |
| Guests, Meet, reminders | none |
| Times | built by `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/calendar_call.py create --zone <event zone> --start "<start>" --end "<end>" --summary "<title>" --color 8 --free --description "<description>"`, passed unchanged |
| Calendar | Riley's connector with `calendarId: "paul@cheek.org"`, per `calendar-sop` |

The description is the "comments" Paul reads. ALWAYS use this template, destination time
first because his watch is on destination time:

```markdown
<context line: e.g. "Flight BOS-LHR, 9:55pm-9:45am London">
Body clock: <body_from> to <body_to> (what your body thinks it is)

<3 to 6 imperative lines from the rules below, only those that apply>

Created by jet-lag-plan: <trip key>
```

Rules for the instruction lines:

- **Light:** `seek` = outside or bright light, with the clock times from `light[]`. `avoid` =
  sunglasses, dim lights, screens away from the face. Leave `neutral` out.
- **Sleep block, in flight:** skip the meal service, mask and earplugs, phone on airplane
  mode. Last caffeine at `caffeine_cutoff`. Wake 45 minutes before landing: water, light,
  coffee with the pre-landing breakfast.
- **Sleep block, layover:** hotel or lounge, alarm set 30 minutes before the end. Melatonin
  only where `melatonin` is `yes`: 0.5 to 3 mg, 30 minutes before lights-out.
  Prescription-only in Singapore, South Korea, the UK and Australia, and unapproved in
  Japan: it applies there only if he already carries it.
- **Awake block, in flight or layover:** an awake stretch through body night means stay up
  and keep the cabin light on; if he crashes, one nap of 45 minutes or less. Eat on destination
  time; on a layover that lands at destination dinner or breakfast, eat.
- **First flight's Awake block:** when `first_flight_body_night_awake_h` is 3 or more, say to
  nap for 60 to 90 minutes on departure day, ending at least 6 hours before takeoff. Naps
  don't trigger the caffeine rule.
- **Last Awake block before landing:** light on arrival; name the low window from `days[0]`
  and the step 5 flags if any; no nap after landing, or 20 minutes before 1pm. Say he lands
  with `residual_shift_at_landing_h` still to go.

## 7. Report

One short message, no preamble:

1. First line: the trip key and any email-versus-calendar discrepancy.
2. `Shift <need_h>h <later|earlier>. Body on <body zone>. You land with <residual>h left to go.`
3. Each script warning, verbatim in meaning.
4. Arrival-day flags from step 5.
5. Blocks created, with times in Paul's local zone and Boston in parentheses
   (`tz.py show <iso> --local <zone>`).

Offer nothing else. If `warnings` says in-flight sleep is short or impossible, say what to
change (a different flight time is Paul's call; never rebook).

## Old patterns

Earlier versions of this plan titled blocks `Jet lag: sleep` and used Sage (`colorId` 2) and
Tomato (11). Do not reproduce those. All blocks are gray and free. Versions that wrote pre-trip nights and post-landing days were dropped: Paul wants flights and layovers only.
