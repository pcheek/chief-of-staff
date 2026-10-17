# Learned rules (promoted)

Rules Paul confirmed in scheduled runs. Each one held for at least two runs, then reached
this file through a reviewed PR (`/calendar-manager:promote-guidance`). They override the
SOP where the two conflict, and never override the guardrails.

- **No lunch checks** (G2, 2026-10-02). Never flag, note or propose anything about lunch.
- **Locations for in-person events** (G4, 2026-10-02). Look the venue up with the
  connectors. Solo events get the address; events with guests get a same-title FYI event
  that holds only the location. Never guess an address.
- **Working location follows the commute** (G5, 2026-10-02). Set through
  `scripts/working_location.py`; see the SOP's Working location section.
- **Commute titles** (G7, 2026-10-02). `Commute to <destination> (From <origin>)`, with the
  destination as the location.
- **Decisions live on the Calendar Decisions page** (G6, 2026-10-02). Runs apply what Paul
  approved there and queue every new proposal there, with a confidence score.

Promoted at Paul's direct request on 2026-10-02, ahead of the usual two-run wait.

## Routed from the email migration (Paul approved the mapping on 2026-10-17)

These came from the retiring sourcery and Slashy mail rules. They are not run-held rules, so they carry
the source id and not a G number.

- **In-person invite where Paul will not be** (Slashy Z10). When a calendar invite is in person, compare
  its location with his travel (flight and hotel emails, travel blocks, out-of-office events). If he will
  not be in that vicinity that day, conflict-scanner writes a Needs Review note and queues a Decisions
  item. It never declines.
- **Restaurant reservations** (sourcery S20). A reservation confirmation in his mail is documented as a
  solo event: title `Dinner: <venue>` or `Lunch: <venue>`, exact time, the venue's address, free or busy
  as the reservation implies, no guests. Never invent a time. The email labeler leaves the thread in his
  inbox.
- **Trip data for outreach** (Slashy Z11). travel-planner keeps the trip city and dates in the run report,
  so the email outreach sweep can offer to find people to meet there. It does not email anyone.
- **Travel buffers** (Slashy Z16). Dropped. The commute and travel rules in this file and the SOP win.

