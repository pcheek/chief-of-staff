# Formats

Consistent title formats are part of what makes Paul's calendar readable at a glance. Only
retitle solo events. On events with guests, the title is shared, so suggest the change
instead.

## Titles

| Kind | Format | Example |
|---|---|---|
| Commute | `Drive time` (to/from implied by time of day) | `Drive time` |
| Flight | `Flight: <FROM> to <TO> (<carrier> <number>)` | `Flight: BOS to SFO (UA 1234)` |
| Train | `Train: <service> <FROM> to <TO>` | `Train: Acela BOS to NYP` |
| Bus | `Bus: <operator> <FROM> to <TO>` | `Bus: Concord Coach BOS to PWM` |
| Long drive (>1h) | `Drive: <FROM> to <TO>` | `Drive: Boston to Portland ME` |
| Airport transit | `Drive to <airport>` | `Drive to Logan` |
| Post-landing buffer | `Buffer: landing delay` | |
| Airport downtime | `Airport: <airport>` | `Airport: SFO` |
| Trip | `Travel: <city>` (all-day) | `Travel: London` |
| Note for Paul | `NOTE: <what needs attention>` | `NOTE: 2 meetings overlap Tue 2pm` |
| Deep work | `Deep work` | |
| Lunch | `Lunch` | |
| WFH | `WFH` (all-day) | |

Never put `commute` or `drive time` in a `Drive:` title. The guard reads those words as a
commute and blocks Callie.

## Descriptions

In-person meeting:
```
In person
Address: <street address>
Directions: <Google Maps link>
Arrival: <MIT building/room, parking, check-in notes>
Backup Zoom: <Paul's personal Zoom link>
Time zone: <if anyone is outside ET>
Context: <non-confidential summary of the email thread>
```

Virtual meeting: the location is Paul's personal Zoom link. The description holds context
and time zone.

Flight:
```
<carrier> <number>, confirmation <code>
Departs <airport> <local time>, arrives <airport> <local time>
Seat <x>, terminal <x>
Source: <email subject + date>
```

Note for Paul (red):
```
What: <the issue>
Why it matters: <the rule it breaks>
Proposed fix: <one concrete option>
Question: <id from guidance.py>
```
