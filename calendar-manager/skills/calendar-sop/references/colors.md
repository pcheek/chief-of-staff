# Color categories

Google Calendar event colors map to these `colorId` values. The guard reads the travel color
from `~/.claude/calendar-manager/config.json` (`travel_color_ids`, default `["1"]`). If you
change the travel color here, change it there too.

| Category | Google name | colorId | Use for |
|---|---|---|---|
| Regular meetings | Blueberry | 9 | Scheduled meetings, 1:1s, calls |
| Deep work / personal time | Basil | 10 | Morning deep work, focus blocks, personal time |
| Family time | Grape | 3 | Dinner with Kyla and Cora, family events |
| Travel time | Lavender | 1 | Commutes, drive time, airport transit, flights, trains, all-day `Travel:` events |
| Speaking / teaching | Banana | 5 | Keynotes, classes, workshops, anything that needs prep |
| Review / action / hold / OOO | Tomato | 11 | Notes for Paul, holds, items to act on, out-of-office where meetings should be declined |
| Downtime in transit | Graphite | 8 | Waiting at the airport, layovers; Callie's personal invites |

Unused: Sage (2), Flamingo (4), Tangerine (6), Peacock (7). If you find an event in one of
these, leave it alone and ask what it means. Paul may have a category this file doesn't know.

## Open conflicts (seeded as questions on the first run)

- Notes: the 2024 doc says purple, the Apr 2025 SOP says red. Red is the default.
- Airport transit: the SOP's flight steps say purple, its legend says lavender. Lavender is
  the default.
