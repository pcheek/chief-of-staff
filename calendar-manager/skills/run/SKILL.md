---
name: run
description: "Scheduled-task entry point for calendar-manager. Invoke as /calendar-manager:run daily, /calendar-manager:run weekly, or add dry-run to report without changing anything. Loads Paul's calendar SOP and learned guidance, dispatches the calendar agents (conflict scanner, commute planner, travel planner, categorizer, notes reviewer, and weekly the 1:1 auditor), merges their questions, writes a run report, and ends by asking Paul the open questions in this session. When Paul replies, record his answers with the guidance skill so the agents learn."
---

# calendar-manager run

This is the prompt a Claude scheduled task fires. Invoking it marks the session as guarded:
the plugin's hook then blocks deletes, invites (Callie on travel aside), RSVPs and outbound
messages for the rest of the session.

`$ARGUMENTS`: `daily` (the default) or `weekly`, optionally with `dry-run`.

## Steps

1. **Set up.**
   - Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guidance.py" init`. It's idempotent, and on
     the first run it seeds questions about gaps in the SOP.
   - Get today's date and time in America/New_York.
   - If no Google Calendar connector is available, stop and say so.
2. **Load context.** Read `${CLAUDE_PLUGIN_ROOT}/skills/calendar-sop/SKILL.md`, then
   `~/.claude/calendar-manager/guidance.md` and `questions.md`.
3. **Dispatch agents in parallel** with the Agent tool. Give each one the mode, the window
   (daily: now plus 48 hours; weekly: today through the end of the week after next),
   `dry-run` if set, and the current date.
   - daily: `conflict-scanner`, `commute-planner`, `travel-planner`, `categorizer`,
     `notes-reviewer`
   - weekly: all of those, plus `one-on-one-auditor`

   Agents that write the same events run in this order instead: travel-planner, then
   commute-planner, then categorizer. That way colors are applied last.
4. **Merge** each agent's final JSON block. Deduplicate actions and proposals.
5. **Write the report** to `~/.claude/calendar-manager/runs/<YYYY-MM-DD>-<mode>.md`, with
   these sections:
   - Changes made (drive-time moves first, each with "check childcare")
   - Proposals for Paul
   - Questions
   - Rules applied
6. **Tick:** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guidance.py" tick` (skip this in a dry
   run).
7. **Reply to Paul.** This message is all he sees. Keep it short, in this order:
   - One line: what changed, as counts.
   - Childcare flags, if any.
   - Proposals, one line each.
   - **Questions**: run `guidance.py open`. Number them with their IDs (`Q7`), each with its
     default in brackets.

     Finish with: "Reply in this chat (for example 'Q7: red. Q9: skip Fridays') and I'll
     save it so I do it that way from now on."

   If there's nothing to report and no open questions, say so in one line.

## When Paul replies in this session

Use the `guidance` skill: record every answer, then act on it now. The session stays
guarded, so the same guardrails apply.

## Never

- Delete events, invite anyone except Callie on qualifying travel, RSVP, or message anyone.
  The hook enforces this. If a call is denied, the answer is a question, not a workaround.
- Re-ask a question that's already open. `guidance.py ask` deduplicates, and the report
  shows how many times each one has come up.
