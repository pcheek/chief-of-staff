---
name: guidance
description: "Turns Paul's answers to calendar-manager questions into durable rules the calendar agents follow from then on. Use whenever Paul replies to a calendar-manager run (for example Q7 red, Q9 skip Fridays), corrects something an agent did, or says how he wants his calendar handled going forward, in the scheduled-task session or via /calendar-manager:guidance. Pulls the memory repo, records each answer with guidance.py and pushes it immediately, then applies the decision now within the guardrails."
---

# Record Paul's calendar guidance

Every answer Paul gives should only ever need to be given once.

Paul often replies hours after the run, after the cloud container has been recycled and
other runs have pushed. So pull first, and push each answer the moment it's recorded.
Never batch answers for the end of the conversation.

`G` = `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/guidance.py"`

## Steps

0. `G sync pull`. If it fails, say so, record anyway, and push at step 2b.
1. Run `G open` to see which questions are pending, and match Paul's reply to their IDs. If
   he answers without an ID, match by topic. If it's still ambiguous, ask him which question
   he means. Never guess.
2. For each answer, write the rule the agents will follow. It should be general,
   imperative, and specific enough to act on without the question:
   - Answer "Sage", to "which color for gym time": rule
     `Gym and workouts are Deep Work / Personal (Sage, colorId 2).`
   - Answer "skip it", to "drive time on 10/9?": rule
     `No drive-time blocks on days whose only in-person event is a dinner.`

   A rule that mentions a time names its zone, or says "local", meaning wherever Paul is
   that day. "No meetings before 9" becomes `No meetings before 9am local time`, unless he
   meant Boston.

   Then save it:
   `G answer Q7 --answer "<his words>" --rule "<the rule>" --scope <agent name, or all>`

   2b. Push it right away, one answer at a time:
   `G sync push --message "answer Q7"`. If it fails, tell Paul the answer is saved only in
   this container, and retry before you finish.
3. A correction with no question attached ("don't color Callie's stuff"):
   `G add-rule --rule "..." --scope <agent>`, then `G sync push --message "rule G12"`.
4. A correction to an existing rule: `G rules`, then `G supersede G4 --rule "..."`, then
   `G sync push --message "supersede G4"`.
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
