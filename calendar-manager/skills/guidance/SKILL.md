---
name: guidance
description: "Turns Paul's answers to calendar-manager questions into durable rules the calendar agents follow from then on. Use whenever Paul replies to a calendar-manager run (for example Q7 red, Q9 skip Fridays), corrects something an agent did, or says how he wants his calendar handled going forward, in the scheduled-task session or via /calendar-manager:guidance. Records each answer with guidance.py, resolves the question, then applies the decision now within the guardrails."
---

# Record Paul's calendar guidance

Every answer Paul gives should only ever need to be given once.

`G` = `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guidance.py"`

## Steps

1. Run `G open` to see which questions are pending, and match Paul's reply to their IDs. If
   he answers without an ID, match by topic. If it's still ambiguous, ask him which question
   he means. Never guess.
2. For each answer, write the rule the agents will follow. It should be general,
   imperative, and specific enough to act on without the question:
   - Answer "red", to "which color for notes": rule
     `Notes and holds for Paul are red (Tomato, colorId 11). Purple is family only.`
   - Answer "skip it", to "drive time on 10/9?": rule
     `No drive-time blocks on days whose only in-person event is a dinner.`

   Then save it:
   `G answer Q7 --answer "<his words>" --rule "<the rule>" --scope <agent name, or all>`
3. A correction with no question attached ("don't color Callie's stuff"):
   `G add-rule --rule "..." --scope <agent>`
4. A correction to an existing rule: `G rules`, then `G supersede G4 --rule "..."`.
5. **Apply now.** Do what the answer decided, for the events it concerns, within the
   guardrails. Usually that means dispatching the agent the question came from with the new
   rule.
6. Confirm in one line per answer: `Q7 -> G12: <rule>`. Done.

## Limits

- No rule can loosen the guardrails. If Paul asks for something the hook blocks, such as
  deleting an event, inviting someone, or emailing someone:
  - Tell him it's blocked by design, and that he can do it himself.
  - Then record the preference that still applies, for example "propose deleting duplicates
    in the report".
- Never record passwords, credentials, compensation, or HR matters as guidance.
