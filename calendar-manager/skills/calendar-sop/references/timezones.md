# Time zones

Paul's home zone is **America/New_York** (Boston). He travels often, so on any given day
"local" means wherever he actually is. Every agent follows these rules. The guard rejects
any timed event written without an explicit UTC offset.

## Where is Paul on a given day?

His location timeline comes from the calendar, checked in this order:

1. **An all-day `Travel: <city>` event covering the date.** The zone is the `Time zone:` line
   in its description. If the description has none, use `tz.py zone-of "<city>"`.
2. **A flight, train or bus that day.** He's in the departure zone before it and the arrival
   zone after it.
3. **Otherwise**, home: America/New_York.

If two sources disagree, or a city isn't in the table below, ask Paul. Don't guess. A wrong
zone moves every event that day.

## Rules

- **Always write offsets.** Every `startTime`/`endTime` you send carries an explicit offset
  (`2026-11-03T14:00:00+00:00`). Get it from `tz.py to-iso "<wall time>" --zone <IANA>`.
  Never type an offset by hand, never send a naive time, never use `GMT`, `EST` or `EDT` as a
  zone name.
- **Cross-zone events: no `timeZone` field.** A flight leaving Boston and landing in London
  has a `-04:00` start and a `+01:00` end. The connector's single `timeZone` field overrides
  both offsets, so leave it out. Use `timeZone` only when start and end are in the same zone.
- **DST is real.** The US and Europe change clocks on different weekends, and the Southern
  Hemisphere changes in the opposite direction. `tz.py` exits 2 when a wall time doesn't
  exist or happens twice. Treat that as a question, not a guess.
- **Personal rules follow Paul, in his local zone.** Deep work first thing, lunch, back-to-back
  meetings, no orphan gaps, and the no-meetings-before-7am / after-8pm comfort window all
  apply in wherever he is that day.
- **Boston-only rules apply only at home:** the MIT commute, dinner at 6pm with Kyla and Cora,
  Friday WFH, in-person 1:1s, and the Tuesday-to-Thursday 1-2pm booking windows. While he's
  away, skip them.
- **Thursday-morning European calls** are Boston mornings when he's home. When he's in
  Europe, they're simply his local business hours.
- **Remote meetings while traveling.** A meeting that is fine in Boston can land at 5am where
  he is. Flag any meeting that starts before 7am or ends after 9pm in his local zone.
- **Other people's zones.** When a meeting includes someone outside Paul's local zone, put
  both times in the description, e.g. `Time zone: 2:00pm GMT for you / 9:00am ET for Jane`.
- **Times in email.** Resolve "Tuesday at 2" in this order:
  1. The zone the sender wrote ("2pm GMT", "2pm my time" plus their known location).
  2. The zone the scheduler wrote on Paul's behalf.
  3. The zone Paul was in when the message was sent, per the location timeline.

  If none of those settles it, ask.
- **Reports to Paul** show times in his zone that day with Boston in parentheses:
  `tz.py show <iso> --local <zone>` gives `Tue Nov 3, 2:00pm GMT (9:00am Boston)`.
- **Searching a day.** Query a local day with `tz.py day-window --date D --zone Z`. Never
  assume a day runs midnight to midnight Eastern while he's in another zone.

## Common cities

`tz.py zone-of` reads this table. Add a row (city names comma-separated) when Paul confirms a
new place. The promote-guidance PR is how it grows.

| City | IANA zone |
|---|---|
| Boston, Cambridge, MIT, Babson, Wellesley, New York, NYC, Washington, DC, Philadelphia, Miami, Atlanta, Toronto | America/New_York |
| Chicago, Austin, Dallas, Houston, Minneapolis | America/Chicago |
| Denver, Boulder, Salt Lake City | America/Denver |
| Phoenix | America/Phoenix |
| San Francisco, SF, Palo Alto, Los Angeles, LA, Seattle, Portland OR | America/Los_Angeles |
| Honolulu | Pacific/Honolulu |
| London | Europe/London |
| Aberdeen, Edinburgh, Glasgow | Europe/London |
| Dublin | Europe/Dublin |
| Lisbon | Europe/Lisbon |
| Paris | Europe/Paris |
| Amsterdam | Europe/Amsterdam |
| Berlin, Munich | Europe/Berlin |
| Madrid, Barcelona | Europe/Madrid |
| Rome, Milan | Europe/Rome |
| Zurich, Geneva | Europe/Zurich |
| Copenhagen | Europe/Copenhagen |
| Stockholm | Europe/Stockholm |
| Helsinki | Europe/Helsinki |
| Athens | Europe/Athens |
| Istanbul | Europe/Istanbul |
| Tbilisi | Asia/Tbilisi |
| Tel Aviv | Asia/Jerusalem |
| Dubai, Abu Dhabi | Asia/Dubai |
| Mumbai, Bangalore, Delhi | Asia/Kolkata |
| Singapore | Asia/Singapore |
| Hong Kong | Asia/Hong_Kong |
| Tokyo | Asia/Tokyo |
| Seoul | Asia/Seoul |
| Sydney | Australia/Sydney |
| Melbourne | Australia/Melbourne |
| Auckland | Pacific/Auckland |
| Mexico City | America/Mexico_City |
| Sao Paulo | America/Sao_Paulo |
