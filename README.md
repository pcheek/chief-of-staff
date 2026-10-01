# chief-of-staff

Paul Cheek's personal Claude Code marketplace. These are plugins for Paul's own calendar and
life admin, kept apart from the Cheek LLC team marketplace because so much of what's in them
is personal.

## Install

```
/plugin marketplace add pcheek/chief-of-staff
/plugin install calendar-manager@chief-of-staff
```

## Plugins

| Plugin | Source | What it does |
|---|---|---|
| `calendar-manager` | bundled (`./calendar-manager`) | Six agents run Paul's calendar SOP from a Claude scheduled task: conflict and overscheduling scans, commute drive-time, fully documented travel, color coding and free/busy, notes review, and 1:1 audits. When an agent is unsure, it asks in that task's chat, and each answer becomes a rule every later run follows. A hook blocks deletes, invites (except Callie on flights, trains, buses, long drives and all-day travel), RSVPs and outbound messages, so agents can only create solo events and recolor or re-mark free/busy on everything else. |

## Before you push

```
python3 scripts/check_marketplace.py
python3 -m unittest discover -s calendar-manager/tests
```

| Limit | Max |
|---|---|
| `description` in `.claude-plugin/plugin.json` and `marketplace.json` | **500** characters |
| `description` in a skill's `SKILL.md` frontmatter | **1024** characters, no XML-like tags |
