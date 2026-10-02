# Color categories

These match Paul's **Legend** calendar, which holds one sample event per category in its
color. If the Legend and this file ever disagree, the Legend wins: ask Paul, then fix this
file through `/calendar-manager:promote-guidance`.

The guard reads only the travel color, from its config (`travel_color_ids`, default
`["1"]`). That's the `CALENDAR_MANAGER_CONFIG_JSON` environment variable in the cloud,
`config.json` on the desktop. If you change the travel color here, change it there too.

| Legend | colorId | Google name | Use for |
|---|---|---|---|
| 🚘 Travel | 1 | Lavender | Commutes, drive time, transfers (Blacklane), airport transit, flights, trains, buses, hotels, all-day `Travel:` events |
| 😎 Deep Work / Personal | 2 | Sage | Morning deep work, focus blocks, personal time |
| 🧑‍🧑‍🧒‍🧒 Family | 3 | Grape | Dinner with Kyla and Cora, evening routine, date night, family events |
| 🎤 Speaking / Teaching | 5 | Banana | Classes, keynotes, workshops, sessions Paul delivers, anything that needs prep |
| ⛔ Do Not Schedule (DNS) | 8 | Graphite | Time that must stay unbooked: airport downtime, standing at an event (book signings), "DNS" blocks. Always busy. Never schedule into it. |
| 🚨 Needs Review | 11 | Tomato | `NOTE:` and `HOLD:` events, items Paul must review or act on, out-of-office where meetings should be declined |
| 📅 Meetings, 👀 Awareness | none | calendar default | Every meeting (1:1s, recurring syncs, calls, anything with guests), plus FYI and awareness items. **Never set a colorId on these.** |

## Rules

- **Meetings get no color.** Never color a meeting. If a meeting already carries a color,
  leave it and propose the change to Paul. The connector can't reliably clear a color.
- **Never assign 4 (Flamingo), 6 (Tangerine), 7 (Peacock), 9 (Blueberry) or 10 (Basil).**
  Peacock shows up in the Legend for meetings, but Paul's rule is no color. If an event is
  already in one of these colors, leave it and ask once about that kind of event.
- **Callie's personal invites** (organizer calliemcheek@gmail.com) keep whatever color they
  arrive with. Never recolor them.
- **Never recolor the past.** Only events that haven't started yet are touched, and the guard
  enforces it.
