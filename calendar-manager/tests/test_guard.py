"""Tests for scripts/guard.py. Run: python3 -m unittest discover -s calendar-manager/tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GUARD = os.path.join(HERE, "..", "scripts", "guard.py")
CAL = "mcp__Google_Calendar__"
CALLIE = "calliemcheek@gmail.com"


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, CALENDAR_MANAGER_HOME=self.tmp.name)
        self.sid = "sess-1"

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, event, raw=None):
        out = subprocess.run([sys.executable, GUARD], input=raw or json.dumps(event),
                             capture_output=True, text=True, env=self.env, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def guard_session(self, sid=None):
        self.run_hook({"hook_event_name": "UserPromptSubmit", "session_id": sid or self.sid,
                       "prompt": "/calendar-manager:run daily"})

    def pre(self, tool, tool_input, sid=None, **extra):
        ev = {"hook_event_name": "PreToolUse", "session_id": sid or self.sid,
              "tool_name": tool, "tool_input": tool_input}
        ev.update(extra)
        out = self.run_hook(ev)
        if not out:
            return "allow"
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]

    def post(self, tool, response, sid=None):
        self.run_hook({"hook_event_name": "PostToolUse", "session_id": sid or self.sid,
                       "tool_name": tool, "tool_input": {}, "tool_response": response})

    def see_event(self, ev):
        self.post(CAL + "get_event", [{"type": "text", "text": json.dumps(ev)}])

    # ---- scope

    def test_unguarded_session_passes_everything(self):
        self.assertEqual(self.pre(CAL + "delete_event", {"eventId": "x"}), "allow")
        self.assertEqual(self.pre(CAL + "create_event", {
            "summary": "Sync", "startTime": "2026-10-02T10:00:00-04:00",
            "endTime": "2026-10-02T11:00:00-04:00",
            "attendees": [{"email": "someone@example.com"}]}), "allow")

    def test_plugin_agent_is_guarded_without_marker(self):
        self.assertEqual(self.pre(CAL + "delete_event", {"eventId": "x"},
                                  agent_type="calendar-manager:categorizer"), "deny")

    def test_marker_only_guards_its_own_session(self):
        self.guard_session("other")
        self.assertEqual(self.pre(CAL + "delete_event", {"eventId": "x"}), "allow")

    # ---- hard denies

    def test_delete_denied_on_any_calendar_server(self):
        self.guard_session()
        for tool in (CAL + "delete_event", "mcp__org-connector-google_calendar__delete_event"):
            self.assertEqual(self.pre(tool, {"eventId": "x"}), "deny")

    def test_rsvp_denied(self):
        self.guard_session()
        self.assertEqual(self.pre(CAL + "respond_to_event",
                                  {"eventId": "x", "responseStatus": "declined"}), "deny")

    def test_reads_allowed(self):
        self.guard_session()
        for action in ("list_events", "get_event", "search_events", "list_calendars",
                       "suggest_time"):
            self.assertEqual(self.pre(CAL + action, {}), "allow")

    def test_malformed_input_denied_when_guarded(self):
        self.guard_session()
        self.assertEqual(self.pre(CAL + "create_event", "not a dict"), "deny")

    def test_outbound_messages_denied_drafts_allowed(self):
        self.guard_session()
        self.assertEqual(self.pre("mcp__Gmail__send_message", {"to": "a@b.c"}), "deny")
        self.assertEqual(self.pre("mcp__Gmail__reply", {}), "deny")
        self.assertEqual(self.pre("mcp__Slack__slack_send_message", {}), "deny")
        self.assertEqual(self.pre("mcp__Gmail__create_draft", {}), "allow")

    def test_raw_calendar_api_denied(self):
        self.guard_session()
        self.assertEqual(self.pre("Bash", {"command":
            "curl -X DELETE https://www.googleapis.com/calendar/v3/calendars/primary/events/x"}),
            "deny")
        self.assertEqual(self.pre("Bash", {"command": "ls"}), "allow")

    def test_guard_state_off_limits(self):
        self.guard_session()
        state = os.path.join(self.tmp.name, "state", "created_events.json")
        self.assertEqual(self.pre("Write", {"file_path": state, "content": "{}"}), "deny")
        self.assertEqual(self.pre("Write", {"file_path": os.path.join(self.tmp.name,
                                                                      "config.json")}), "deny")
        self.assertEqual(self.pre("Bash", {"command": "echo {} > ~/.claude/calendar-manager/"
                                                      "state/created_events.json"}), "deny")

    # ---- create

    def test_solo_create_allowed(self):
        self.guard_session()
        self.assertEqual(self.pre(CAL + "create_event", {
            "summary": "Drive time", "colorId": "1",
            "startTime": "2026-10-02T08:00:00-04:00", "endTime": "2026-10-02T09:00:00-04:00"}),
            "allow")

    def test_create_with_guest_denied(self):
        self.guard_session()
        self.assertEqual(self.pre(CAL + "create_event", {
            "summary": "1:1", "startTime": "2026-10-02T10:00:00-04:00",
            "endTime": "2026-10-02T10:30:00-04:00",
            "attendees": [{"email": "colleague@mit.edu"}]}), "deny")
        self.assertEqual(self.pre(CAL + "create_event", {
            "summary": "x", "startTime": "a", "endTime": "b",
            "attendeeEmails": ["colleague@mit.edu"]}), "deny")

    def test_create_with_meet_or_room_or_other_calendar_denied(self):
        self.guard_session()
        base = {"summary": "x", "startTime": "2026-10-02T10:00:00-04:00",
                "endTime": "2026-10-02T10:30:00-04:00"}
        self.assertEqual(self.pre(CAL + "create_event", dict(base, addGoogleMeetUrl=True)),
                         "deny")
        self.assertEqual(self.pre(CAL + "create_event", dict(
            base, attendees=[{"email": "room-170@resource.calendar.google.com",
                              "resource": True}])), "deny")
        self.assertEqual(self.pre(CAL + "create_event", dict(base, calendarId="kyla@x.com")),
                         "deny")

    def test_paul_himself_is_not_a_guest(self):
        self.guard_session()
        self.assertEqual(self.pre(CAL + "create_event", {
            "summary": "Deep work", "startTime": "2026-10-02T07:00:00-04:00",
            "endTime": "2026-10-02T09:00:00-04:00",
            "attendees": [{"email": "Paul@cheek.org"}]}), "allow")

    # ---- Callie

    def callie_create(self, summary, start, end, color="1", all_day=False, extra=None):
        ti = {"summary": summary, "colorId": color, "startTime": start, "endTime": end,
              "attendees": [{"email": CALLIE}] + (extra or [])}
        if all_day:
            ti["allDay"] = True
        return self.pre(CAL + "create_event", ti)

    def test_callie_flight_train_bus_allowed(self):
        self.guard_session()
        for s in ("Flight: BOS to SFO (UA 123)", "Train: Acela to NYP", "Bus: Concord Coach"):
            self.assertEqual(self.callie_create(s, "2026-10-13T10:45:00-04:00",
                                                "2026-10-13T12:09:00-04:00"), "allow", s)

    def test_callie_long_drive_allowed_short_drive_denied(self):
        self.guard_session()
        self.assertEqual(self.callie_create("Drive: Boston to Portland ME",
                                            "2026-10-13T09:00:00-04:00",
                                            "2026-10-13T11:00:00-04:00"), "allow")
        self.assertEqual(self.callie_create("Drive: to Logan", "2026-10-13T09:00:00-04:00",
                                            "2026-10-13T10:00:00-04:00"), "deny")

    def test_callie_never_on_commute(self):
        self.guard_session()
        self.assertEqual(self.callie_create("Drive: commute to MIT", "2026-10-13T07:00:00-04:00",
                                            "2026-10-13T09:00:00-04:00"), "deny")
        self.assertEqual(self.callie_create("Drive time", "2026-10-13T07:00:00-04:00",
                                            "2026-10-13T09:00:00-04:00"), "deny")

    def test_callie_all_day_travel_allowed(self):
        self.guard_session()
        self.assertEqual(self.callie_create("Travel: San Francisco", "2026-10-13", "2026-10-16",
                                            all_day=True), "allow")
        self.assertEqual(self.callie_create("Offsite", "2026-10-13", "2026-10-16",
                                            all_day=True), "deny")

    def test_callie_needs_travel_color(self):
        self.guard_session()
        self.assertEqual(self.callie_create("Flight: BOS to SFO", "2026-10-13T10:45:00-04:00",
                                            "2026-10-13T12:09:00-04:00", color="9"), "deny")

    def test_callie_plus_anyone_else_denied(self):
        self.guard_session()
        self.assertEqual(self.callie_create("Flight: BOS to SFO", "2026-10-13T10:45:00-04:00",
                                            "2026-10-13T12:09:00-04:00",
                                            extra=[{"email": "friend@example.com"}]), "deny")

    def test_add_callie_to_solo_all_day_travel_event(self):
        self.guard_session()
        upd = {"eventId": "trip1", "addedAttendees": [{"email": CALLIE}]}
        self.assertEqual(self.pre(CAL + "update_event", upd), "deny")  # not verified yet
        self.see_event({"id": "trip1", "summary": "Travel: London", "colorId": "1",
                        "start": {"date": "2026-11-02"}, "end": {"date": "2026-11-06"},
                        "organizer": {"email": "paul@cheek.org", "self": True}})
        self.assertEqual(self.pre(CAL + "update_event", upd), "allow")

    def test_add_callie_to_commute_denied_even_if_solo(self):
        self.guard_session()
        self.see_event({"id": "c1", "summary": "Commute", "colorId": "1",
                        "start": {"dateTime": "2026-11-02T07:00:00-05:00"},
                        "end": {"dateTime": "2026-11-02T08:00:00-05:00"}})
        self.assertEqual(self.pre(CAL + "update_event", {
            "eventId": "c1", "addedAttendees": [{"email": CALLIE}]}), "deny")

    # ---- Gmail-driven agents

    def test_gmail_reads_allowed(self):
        self.guard_session()
        for tool in ("mcp__Gmail__search_threads", "mcp__Gmail__get_thread",
                     "mcp__org-connector-gmail__get_message"):
            self.assertEqual(self.pre(tool, {"query": "filename:ics"}), "allow", tool)

    def test_new_agents_guarded_without_marker(self):
        for agent in ("calendar-manager:invite-reconciler", "offered-times-tracker"):
            self.assertEqual(self.pre(CAL + "delete_event", {"eventId": "x"},
                                      agent_type=agent), "deny", agent)

    def test_missing_invite_placeholder_allowed(self):
        self.guard_session()
        self.assertEqual(self.pre(CAL + "create_event", {
            "summary": "NOTE: missing invite: Board prep", "colorId": "11",
            "availability": "AVAILABILITY_BUSY", "description": "Invite from x",
            "startTime": "2026-10-05T14:00:00-04:00", "endTime": "2026-10-05T15:00:00-04:00"}),
            "allow")

    def test_release_offered_hold(self):
        self.guard_session()
        self.see_event({"id": "h1", "summary": "HOLD: offered to Jane Doe: podcast",
                        "colorId": "11", "start": {"dateTime": "2026-10-06T14:00:00-04:00"},
                        "end": {"dateTime": "2026-10-06T14:30:00-04:00"}})
        self.assertEqual(self.pre(CAL + "update_event", {
            "eventId": "h1", "summary": "DONE: HOLD: offered to Jane Doe: podcast",
            "availability": "AVAILABILITY_FREE", "notificationLevel": "NONE"}), "allow")

    # ---- update

    def test_color_and_freebusy_on_guest_event_allowed(self):
        self.guard_session()
        self.assertEqual(self.pre(CAL + "update_event", {
            "eventId": "g1", "colorId": "9", "availability": "AVAILABILITY_BUSY",
            "notificationLevel": "NONE"}), "allow")

    def test_update_must_be_silent(self):
        self.guard_session()
        self.assertEqual(self.pre(CAL + "update_event", {"eventId": "g1", "colorId": "9"}),
                         "deny")

    def test_time_edit_on_guest_event_denied(self):
        self.guard_session()
        self.see_event({"id": "g1", "summary": "1:1", "start": {"dateTime": "2026-10-02T10:00:00Z"},
                        "attendees": [{"email": "paul@cheek.org", "self": True},
                                      {"email": "colleague@mit.edu"}]})
        self.assertEqual(self.pre(CAL + "update_event", {
            "eventId": "g1", "startTime": "2026-10-02T11:00:00Z",
            "notificationLevel": "NONE"}), "deny")

    def test_time_edit_after_solo_read_allowed(self):
        self.guard_session()
        self.see_event({"id": "d1", "summary": "Drive time",
                        "start": {"dateTime": "2026-10-02T08:00:00-04:00"},
                        "end": {"dateTime": "2026-10-02T09:00:00-04:00"}})
        self.assertEqual(self.pre(CAL + "update_event", {
            "eventId": "d1", "startTime": "2026-10-02T07:30:00-04:00",
            "notificationLevel": "NONE"}), "allow")

    def test_solo_read_does_not_carry_across_sessions(self):
        self.guard_session()
        self.guard_session("sess-2")
        self.see_event({"id": "d1", "summary": "Drive time",
                        "start": {"dateTime": "2026-10-02T08:00:00-04:00"}})
        self.assertEqual(self.pre(CAL + "update_event", {
            "eventId": "d1", "summary": "Drive", "notificationLevel": "NONE"},
            sid="sess-2"), "deny")

    def test_event_created_by_agents_is_editable(self):
        self.guard_session()
        self.post(CAL + "create_event", {"id": "new1", "summary": "Buffer",
                                         "start": {"dateTime": "2026-10-02T12:00:00-04:00"}})
        self.assertEqual(self.pre(CAL + "update_event", {
            "eventId": "new1", "description": "Lunch buffer", "notificationLevel": "NONE"}),
            "allow")

    def test_attendee_changes_never_allowed(self):
        self.guard_session()
        self.post(CAL + "create_event", {"id": "new1", "summary": "Buffer",
                                         "start": {"dateTime": "2026-10-02T12:00:00-04:00"}})
        for key, val in (("removedAttendeeEmails", ["x@y.z"]),
                         ("addedAttendees", [{"email": "x@y.z"}]),
                         ("addGoogleMeetUrl", True)):
            self.assertEqual(self.pre(CAL + "update_event", {
                "eventId": "new1", key: val, "notificationLevel": "NONE"}), "deny", key)


if __name__ == "__main__":
    unittest.main()
