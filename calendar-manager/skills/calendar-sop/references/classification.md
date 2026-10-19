# Classification is Clef only

**No Claude or Anthropic model classifies anything in calendar-manager.** Every yes/no, category, and ranking judgment is made by Cloudflare's Clef decision model through `scripts/clef_ask.py`. The agents retrieve (calendar, Gmail, Drive), extract (times, addresses, confirmation codes), do arithmetic, build calendar calls, and write. When one of them needs to know *what kind of thing this is* or *whether it is true*, it asks Clef and acts on the answer. It never settles the question itself, and a Clef answer it dislikes is not overridden.

## How to ask

Build one item per thing being judged, with every question about it in the same item. Run:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/clef_ask.py" --json '{"items":[{"id":"<event or email id>","state":{...},"questions":{"<q>":{"type":"noul","instructions":"..."}}}]}'
```

- Write every apostrophe inside the JSON as `'` (valid JSON), so the single-quoted argument never breaks. Keep `state` short: the title, times, location, a description under 1,500 characters, the guest count and the organizer's domain. Never send a private event's details; send the title `Private event` and the times.
- `type` is `noul` (yes/no), `choice` (pick one; needs `criteria`, an object of option to meaning) or `score` (ordered levels in `criteria`, lowest first). 1 to 64 questions per item, every item in one call.
- The answers print as JSON. Per question: `noul` gives `p` and a `verdict` of `yes`, `no` or `unsure`; `choice` gives the top choice, `top_p`, and a `verdict` that is the choice or `unsure`. The script asks the larger Clef model about any gray answer before it returns.
- **Act only on a decisive verdict.** A `yes`, a `no`, or a named choice. On `unsure`, do not decide it: leave the event or note alone, and ask Paul once per kind of thing with `guidance.py ask` (default: leave it alone).
- **Never write a verdict, probability or Clef's wording into an event.** The event's description names the facts and the source, as the formats file says.
- If the command exits 3 (no `CLOUDFLARE_ACCOUNT_ID`) or 4 (Clef failed, or its network secret is missing), **stop and return `"error": "Clef unavailable: <message>"` with no actions.** Never fall back to your own judgment. The orchestrator already stopped the run if Clef was down at the start; this covers a failure mid-run.
- A question can carry a stricter bar for a risky action: `"accept": {"<q>": {"yes_min": 0.95, "no_max": 0.05}}` on the item.

## Question bank

Use these questions as written, so every run asks the same thing. Add a question only for a judgment that isn't here.

| Agent | Item | `state` | Questions |
|---|---|---|---|
| categorizer | one per event with no `NOTE:`, `HOLD:`, `DONE:` or `Jet Lag - ` prefix | title, description, location, start, end, all-day, guest count, recurring, current color | `category` (choice): `travel` "Commutes, drive time, transfers, airport transit, flights, trains, buses, hotels, all-day Travel events"; `deep_work` "Deep work, focus blocks, personal time"; `family` "Dinner with Kyla and Cora, evening routine, date night, family events"; `speaking` "Classes, keynotes, workshops, and sessions Paul delivers or must prepare for"; `dns` "Time that must stay unbooked: airport downtime, standing at an event, DNS blocks"; `needs_review` "Something Paul must review or act on"; `meeting` "A meeting with other people: 1:1s, recurring syncs, calls, anything with guests"; `awareness` "An FYI or awareness item"; `other` "None of these". Map: travel 1, deep_work 2, family 3, speaking 5, dns 8, needs_review 11, everything else no color. Add `in_person` (noul) "Is this event held in person at a physical venue?" when the location is empty, `student_meeting` (noul) "Is this a meeting with a student?" and `virtual_meeting` (noul) "Is this a virtual meeting, a call or video meeting?" when it has guests. |
| conflict-scanner | one per busy event in an overlap | title, description, guest count, organizer domain | `priority` (choice): `teaching_speaking`, `team_one_on_one`, `team_project`, `recruiting`, `student`, `external`, `other`, each with the SOP's meaning. Rank by the SOP's order; Clef never ranks. |
| conflict-scanner | one per pair of adjacent events | both events' titles, locations, in-person hints | `different_places` (noul) "Are these two events held at different physical places, so Paul has to travel between them?" |
| conflict-scanner | one per event in a 1:1 run | title, guest count | `one_on_one` (noul) "Is this a one-on-one meeting between Paul and one other person?" and `lunch` (noul) "Is this lunch or a meal break?" (never flag lunch) |
| commute-planner | one per event with an unclear venue | title, location, description | `in_person_in_commuting_area` (noul) "Is this event held in person at MIT, Cambridge, Boston, or another place in Paul's commuting area?" and, for candidates in step 5, `low_priority_external` (noul) "Is this a low-priority external meeting that could be taken as a phone call?" |
| invite-reconciler | one per email | subject, sender, the first 1,500 characters | `email_kind` (choice): `new_invite`, `updated_invite`, `cancellation`, `response_notice` (accepted, declined, tentative), `not_an_invite` |
| invite-reconciler | one per invite with no iCalUID or `eid` match | the invite's title, organizer, times; the candidate event's title, organizer, times | `same_meeting` (noul) "Are these the same meeting?" |
| notes-reviewer | one per note Paul wrote | the note's title and description | `intent` (choice): `block_time`, `move_my_event`, `recolor`, `retitle_or_describe`, `remind_or_ask_me`, `other` |
| notes-reviewer | one per agent `NOTE:` | the note's text, plus the facts you looked up now (the calendar at that time, the thread) | `problem_resolved` (noul) "Is the problem this note describes fixed?" |
| notes-reviewer | one per `HOLD: offered to` | the offer's slot, the thread's later messages | `thread_status` (choice): `settled_other_time`, `settled_this_slot`, `still_open`, `other`. The 7-day cold rule is date arithmetic; do it yourself. |
| offered-times-tracker | one per email | subject, sender, the first 2,000 characters | `email_kind` (choice): `offers_times`, `accepts_a_proposed_time`, `confirms_a_time`, `booking_link`, `other` |
| offered-times-tracker | one per thread | the thread's messages in order | `status` (choice): `confirmed`, `open`, `other` |
| travel-planner | one per email | subject, sender, the first 2,000 characters | `travel_kind` (choice): `flight`, `train`, `bus`, `hotel`, `rental_car`, `ride_service`, `cancellation_or_change`, `not_travel` |
| travel-planner | one per calendar event with no matching trip | title, description, location, all-day | `undocumented_travel` (noul) "Does this event mark time Paul spends away from home on a trip?" |
| one-on-one-auditor | roster rows are matched by attendee address, a rule. Clef is asked only for an event with no roster match | title, guest count | `one_on_one` (noul), as above |

## What stays with Claude

Extracting times, addresses, confirmation codes and attendee lists from text it read; resolving relative dates; the arithmetic of windows, offsets and counts (`tz.py`, `calendar_call.py`); retrieval; writing titles, descriptions, and the report; and the human questions to Paul.

## Privacy

State goes to Cloudflare Workers AI, which states zero retention and no training for standard inference (https://developers.cloudflare.com/workers-ai/platform/data-usage/). Keep it to what a question needs. HR, compensation and medical details are never sent; send `Private event` instead.
