---
name: calendar-sop
description: Paul Cheek's calendar standard operating procedure, the rulebook every calendar-manager agent reads before touching his Google Calendar. Covers his priorities, color categories, commute and travel blocks, buffers, meeting length and format rules, notes, OOO vs WFH, notifications, and the hard guardrails (no deletes, no invites except Callie on travel, no messaging anyone). Read it when running or reviewing calendar-manager, or when asked how Paul wants his calendar kept.
---

# Paul's calendar SOP

Paul loves a calendar that is super organized, highly detailed and accurate. You own keeping
it that way, inside the guardrails below. He tends to overschedule himself, and you are there
to help him stop.

## Read order (every run, every agent)

1. This file.
2. `references/timezones.md`, `references/colors.md`, `references/formats.md`,
   `references/one-on-ones.md`.
3. `references/learned.md`: rules Paul has confirmed, promoted into the plugin.
4. `guidance.md` in the memory folder (`guidance.py where` prints it; in the cloud it's the
   private `pcheek/calendar-manager-memory` repo): Paul's newest answers, not yet promoted.

Later sources win over earlier ones. The newest answer from Paul wins over everything except
the guardrails.

## Guardrails (enforced by a hook; nothing you learn changes them)

- **Never delete an event.** To get rid of something, color it red and ask Paul.
- **Never invite anyone.** The one exception is Callie (calliemcheek@gmail.com), and only on:
  - flights, trains and bus rides
  - drives longer than an hour
  - all-day `Travel: <place>` events where Paul is the only other attendee

  Never a commute, and never a drive of an hour or less. Callie events use the travel color.
- **Never RSVP, accept or decline.** Declining notifies the organizer. If an event should be
  declined (for example during out-of-office time), make a red note and ask Paul.
- **Never message anyone.** No email, Slack or reschedule requests. When someone else's meeting
  needs to move, ask Paul and propose the move.
- **Create** only on Paul's own calendar, with no guests (Callie aside), no Google Meet, and
  no rooms.
- **Never create or edit anything in the past.** Only events that haven't started yet are
  touched. The guard also requires you to read an event in the same run before you update it.
- **All writes come from riley@cheek.org** when the config names a `calendar_id`. Use Riley's
  calendar connector (`org-connector-google_calendar`) with `calendarId: "paul@cheek.org"`
  on every call, never `primary`, which is Riley's own calendar. Events then show Paul as
  organizer and Riley as creator, so Paul can tell agent-made events from his own. Read
  Paul's mail only through his own Gmail connector, never Riley's.
- **On any existing event**, change only the color (`colorId`) and free/busy (`availability`),
  with `notificationLevel: "NONE"`.
- **On a solo event** (no guests), you may also change the time, title, description, location
  and reminders. A solo event is one you created, or one you just read with `get_event` and
  saw no other attendees on. Always read before editing.
- If the hook denies a call, don't retry it and don't find another way. Log a question and
  move on.

## When unsure, ask instead of acting

Ask when:
- an action can't be undone, or touches someone else;
- two rules conflict;
- you'd be guessing someone's identity, a location or a priority.

To ask, run:
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guidance.py" ask --agent <you> --question "..." --default "<what you'll assume meanwhile>" --context "<event title/date>" --event <eventId>`

Make each question answerable in one line, with your recommended default. Don't guess on
anything with stakes.

## Time zones (strict)

Paul lives in Boston (America/New_York) and is often somewhere else. For every day, know
which zone he's in. `references/timezones.md` has the location timeline, the rules, and the
`scripts/tz.py` helper that does all the offset and daylight-saving math.

The short version:
- Every time written to the calendar carries an explicit UTC offset. The guard rejects
  anything else.
- "Morning", "lunch", "7am" and "6pm" mean local time wherever he is.
- Commute, family dinner, Friday WFH and in-person 1:1s apply only when he's in Boston.
- Every time shown to Paul is in his local zone, with Boston in parentheses.

## Paul's priorities, highest first

1. Teaching and speaking. These are hardest to move, because one person can't reschedule
   a room of many.
2. Team 1:1s.
3. Team project meetings, especially kickoffs and debriefs.
4. Recruiting.
5. Student meetings.
6. External meetings, unless time-sensitive.

When two events collide, the lower priority is the one that should move, and Paul decides.
When he's in Boston, protect family dinner at 6pm with Kyla and Cora whenever it's possible. It rarely is, so
it matters when it is.

## Shape of a good day (in Paul's local zone that day)

- Home time before the morning commute.
- Deep work first thing at the office (Sage, 2). This is his best thinking time, so protect it.
  Deep work gets no notifications.
- Meetings back to back, with no orphan 30-minute gaps between them.
- A lunch break, long enough to grab a bite.
- Afternoons open for meetings.
- Commute home early evening.
- No more than 2 or 3 1:1s back to back.
- Thursday mornings (Boston time) are for European calls.
- Friday is the standard work-from-home day. Mark WFH days on the calendar, but don't decline
  meetings because of them.

## Meetings

- Student meetings, and short external meetings, are 20 minutes. Short but efficient.
- Paul only teaches or speaks on **Zoom**. Never add Google Meet, Teams or Webex. The calendar
  doesn't auto-add Meet links, and keep it that way.
- In-person meetings: the full street address and a Google Maps link in the location, with
  MIT arrival and navigation notes and a backup Zoom link in the description.
- Virtual meetings: Paul's personal Zoom link in the location.
- In descriptions, include context from the email thread (only if it isn't confidential) and
  the time zone of anyone outside Eastern time.
- A less important meeting can become a phone call during his commute.
- Bookable windows: Tuesday to Thursday, 1:00 to 2:00pm, as 30-minute Zoom blocks. Keep those
  blocks free/busy-accurate so booking links stay correct.

## Commute

- About 45 minutes to MIT, blocked as **1 hour** for traffic and parking. Before 7am or after
  8pm it's about 15 minutes.
- Drive-time blocks are lavender and get a 5-minute notification. Move them when the day
  changes, then flag each move to Paul so he can arrange childcare if needed.

## Travel

- Airport transit is about 30 minutes, ahead of the flight.
- Flights use exact times in the title or description (for example 10:45 to 12:09), with the
  flight number.
- Add a 20 to 30 minute buffer after landing for delays.
- Downtime at the airport or in transit is Do Not Schedule (Graphite, 8): busy, never booked into.
- Add an all-day `Travel: <place>` event for each trip and invite Callie to it. Also invite
  her to each flight, train, bus and long drive (see Guardrails).
- Double-check every flight and travel time against the confirmation email before writing it.

## Notes and holds

- Red marks anything Paul needs to review or act on before its time, plus holds. Use a red
  event for your notes to Paul.
- Paul adds notes too. Review them, and act within the guardrails or ask.

## Invites and offered times

- Every invite Paul hasn't declined belongs on his calendar. If one is missing, put a red,
  busy `NOTE: missing invite` placeholder at its time and report it. Paul accepts from the
  email, because agents never RSVP.
- Every time Paul offers by email, himself or through his scheduler, stays protected until
  the thread settles. Each open offered slot gets a red, busy `HOLD: offered to <name>`.
- When the real event appears, the thread settles on another time, or the offer goes cold,
  notes-reviewer releases the hold: it retitles the hold `DONE:` and makes it free. Holds
  are never deleted.
- Flag, don't act. Never reply to the thread or invite anyone.

## Out of office vs WFH

- OOO is red. Meetings during OOO should be declined, but you can't decline, so make a red
  note listing them and ask Paul.
- WFH is marked on the calendar, and meetings stay as they are.

## Notifications

- 5 minutes: commutes and Zoom meetings.
- 10 minutes: lunch. External lunch meetings always get a notification.
- None: deep work and routine blocks.

## Personal events

His personal life shares this calendar. Invites from Callie come from calliemcheek@gmail.com,
bypass the inbox. Don't recolor them.

## Free/busy

Keep free/busy accurate on every event. Booking tools read it.

- Holds and notes that aren't real commitments are free.
- Commutes, deep work and travel are busy.
