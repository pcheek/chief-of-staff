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
        self.env = dict(os.environ, CALENDAR_MANAGER_HOME=self.tmp.name,
                        CALENDAR_MANAGER_NOW="2026-10-01T12:00:00Z")
        for key in ("CALENDAR_MANAGER_CONFIG", "CALENDAR_MANAGER_CONFIG_JSON"):
            self.env.pop(key, None)
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
        self.assertEqual(self.pre("Bash", {"command": "echo {} > %s" % state}), "deny")

    # ---- protected paths (keyed off the real STATE / CONFIG paths) and git

    def bash(self, command, cwd=None):
        return self.pre("Bash", {"command": command}, cwd=cwd or self.tmp.name)

    def test_inline_code_reading_tool_results_allowed(self):
        self.guard_session()
        home = os.path.expanduser("~")
        tool_result = home + "/.claude/projects/-home-user-mem/abc/tool-results/x.json"
        self.assertEqual(self.bash("python3 -c \"import json;print(json.load(open('%s')))\""
                                   % tool_result), "allow")
        self.assertEqual(self.bash("python3 -c \"open('.claude/settings.json','w')\""), "deny")
        self.assertEqual(self.bash("python3 -c \"open('guard.py').read()\""), "deny")

    def test_state_by_relative_path_from_memory_repo(self):
        self.guard_session()
        self.assertEqual(self.bash("echo {} > state/created_events.json"), "deny")
        self.assertEqual(self.bash("cat ./state/guarded/x"), "deny")
        self.assertEqual(self.bash("cd state && ls"), "deny")

    def test_literal_old_path_is_not_the_check(self):
        # The state lives wherever CALENDAR_MANAGER_HOME says, not in a hardcoded folder.
        self.guard_session()
        self.assertEqual(self.bash("ls /tmp/some/calendar-manager/state-of-things"), "allow")

    def test_config_outside_repo_is_off_limits(self):
        cfg_dir = tempfile.TemporaryDirectory()
        self.addCleanup(cfg_dir.cleanup)
        cfg = os.path.join(cfg_dir.name, "config.json")
        self.env["CALENDAR_MANAGER_CONFIG"] = cfg
        self.guard_session()
        self.assertEqual(self.pre("Write", {"file_path": cfg, "content": "{}"}), "deny")
        self.assertEqual(self.bash("cat %s" % cfg), "deny")
        self.assertEqual(self.bash('echo x > "$CALENDAR_MANAGER_CONFIG"'), "deny")
        self.assertEqual(self.pre("Write", {"file_path": os.path.join(self.tmp.name,
                                                                      "notes.md")}), "allow")

    def test_inline_config_env_wins_over_file(self):
        self.env["CALENDAR_MANAGER_CONFIG_JSON"] = json.dumps({"travel_color_ids": ["5"]})
        self.guard_session()
        self.assertEqual(self.callie_create("Flight: BOS to SFO", "2026-10-13T10:45:00-04:00",
                                            "2026-10-13T12:09:00-07:00", color="5"), "allow")
        self.assertEqual(self.callie_create("Flight: BOS to SFO", "2026-10-13T10:45:00-04:00",
                                            "2026-10-13T12:09:00-07:00", color="1"), "deny")

    def test_memory_repo_code_is_write_protected_but_runnable(self):
        self.guard_session()
        os.makedirs(os.path.join(self.tmp.name, ".claude"), exist_ok=True)
        script = os.path.join(self.tmp.name, ".claude", "calendar-manager", "scripts",
                              "guidance.py")
        self.assertEqual(self.bash("python3 %s ask --agent a --question 'x > y?'" % script),
                         "allow")
        self.assertEqual(self.bash("cp /tmp/x.py %s" % script), "deny")
        self.assertEqual(self.bash("echo '' > .gitignore"), "deny")
        self.assertEqual(self.bash("sed -i s/state// .gitignore"), "deny")
        self.assertEqual(self.bash("python3 -c \"open('.gitignore','w')\""), "deny")
        self.assertEqual(self.pre("Edit", {"file_path": os.path.join(self.tmp.name,
                                                                     ".gitignore")}), "deny")
        self.assertEqual(self.pre("Write", {"file_path": os.path.join(
            self.tmp.name, ".claude", "settings.json")}), "deny")

    def test_git_staging_rules(self):
        self.guard_session()
        self.assertEqual(self.bash("git add guidance.json guidance.md questions.md runs/"),
                         "allow")
        self.assertEqual(self.bash("git add -A && git commit -m 'run 2026-10-05 daily'"),
                         "allow")
        self.assertEqual(self.bash("git add -f state/created_events.json"), "deny")
        self.assertEqual(self.bash("git add --force ."), "deny")
        self.assertEqual(self.bash("git add -Af"), "deny")
        self.assertEqual(self.bash("git add state"), "deny")
        self.assertEqual(self.bash("git add config.json"), "deny")
        self.assertEqual(self.bash("git -C %s add config.json" % self.tmp.name), "deny")
        self.assertEqual(self.bash("git rm --cached .gitignore"), "deny")
        self.assertEqual(self.bash("git checkout HEAD~1 -- .claude/settings.json"), "deny")

    def test_never_force_push(self):
        self.guard_session()
        self.assertEqual(self.bash("git push origin HEAD:main"), "allow")
        self.assertEqual(self.bash("git pull --rebase origin main && git push"), "allow")
        for cmd in ("git push --force", "git push -f origin main",
                    "git push --force-with-lease origin main", "git push origin +main",
                    "git push origin :main", "git push --delete origin main"):
            self.assertEqual(self.bash(cmd), "deny", cmd)

    def test_memory_repo_sessions_are_always_guarded(self):
        open(os.path.join(self.tmp.name, ".calendar-manager-memory"), "w").close()
        self.env.pop("CALENDAR_MANAGER_HOME")
        self.assertEqual(self.pre(CAL + "delete_event", {"eventId": "x"}, cwd=self.tmp.name),
                         "deny")
        sub = os.path.join(self.tmp.name, "runs")
        os.makedirs(sub)
        self.assertEqual(self.pre(CAL + "delete_event", {"eventId": "x"}, cwd=sub), "deny")
        self.assertEqual(self.pre(CAL + "delete_event", {"eventId": "x"},
                                  cwd=tempfile.gettempdir()), "allow")

    def test_vendored_run_prompt_guards_session(self):
        self.run_hook({"hook_event_name": "UserPromptSubmit", "session_id": "v1",
                       "prompt": "/calendar-run daily dry-run"})
        self.assertEqual(self.pre(CAL + "delete_event", {"eventId": "x"}, sid="v1"), "deny")

    # ---- create

    def test_solo_create_allowed(self):
        self.guard_session()
        self.assertEqual(self.pre(CAL + "create_event", {
            "summary": "Drive time", "colorId": "1",
            "startTime": "2026-10-02T08:00:00-04:00", "endTime": "2026-10-02T09:00:00-04:00"}),
            "allow")

    def test_working_location_and_ooo_creates(self):
        self.guard_session()
        wl = {"summary": "MIT", "eventType": "WORKING_LOCATION",
              "workingLocationProperties": {"type": "CUSTOM_LOCATION", "customLocationLabel": "MIT"},
              "startTime": "2026-10-02T07:00:00-04:00", "endTime": "2026-10-02T15:00:00-04:00"}
        self.assertEqual(self.pre(CAL + "create_event", wl), "allow")
        self.assertEqual(self.pre(CAL + "create_event", dict(wl, workingLocationProperties=None)),
                         "deny")
        self.assertEqual(self.pre(CAL + "create_event", dict(
            wl, attendees=[{"email": "calliemcheek@gmail.com"}])), "deny")
        ooo = {"summary": "OOO: Singapore night", "eventType": "OUT_OF_OFFICE",
               "startTime": "2026-10-11T20:00:00+08:00", "endTime": "2026-10-12T07:00:00+08:00"}
        self.assertEqual(self.pre(CAL + "create_event", ooo), "allow")
        self.assertEqual(self.pre(CAL + "create_event", dict(
            ooo, endTime="2026-10-18T07:00:00+08:00")), "deny")  # a whole trip, not one night
        self.assertEqual(self.pre(CAL + "create_event", dict(
            ooo, allDay=True, startTime="2026-10-11", endTime="2026-10-12")), "deny")
        self.assertEqual(self.pre(CAL + "create_event", dict(ooo, eventType="FOCUS_TIME")), "deny")

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

    # ---- strict time zones

    def test_naive_times_denied(self):
        self.guard_session()
        self.assertEqual(self.pre(CAL + "create_event", {
            "summary": "Deep work", "startTime": "2026-10-05T07:00:00",
            "endTime": "2026-10-05T09:00:00"}), "deny")
        self.assertEqual(self.pre(CAL + "create_event", {
            "summary": "Deep work", "startTime": "2026-10-05T07:00:00-04:00",
            "endTime": "2026-10-05T09:00:00"}), "deny")

    def test_cross_zone_flight_with_offsets_allowed(self):
        self.guard_session()
        self.assertEqual(self.callie_create("Flight: BOS to LHR (BA 212)",
                                            "2026-10-13T18:30:00-04:00",
                                            "2026-10-14T06:25:00+01:00"), "allow")

    def test_timezone_field_must_match_offsets(self):
        self.guard_session()
        base = {"summary": "Flight: BOS to LHR", "colorId": "1",
                "startTime": "2026-10-13T18:30:00-04:00", "endTime": "2026-10-14T06:25:00+01:00"}
        self.assertEqual(self.pre(CAL + "create_event", dict(base, timeZone="America/New_York")),
                         "deny")
        self.assertEqual(self.pre(CAL + "create_event", dict(base, timeZone="EST")), "deny")
        london = {"summary": "Dinner", "timeZone": "Europe/London",
                  "startTime": "2026-10-27T19:00:00+00:00", "endTime": "2026-10-27T21:00:00+00:00"}
        self.assertEqual(self.pre(CAL + "create_event", london), "allow")
        # Oct 20 London is still on BST (+01:00); +00:00 is wrong for that zone and date.
        self.assertEqual(self.pre(CAL + "create_event", dict(
            london, startTime="2026-10-20T19:00:00+00:00", endTime="2026-10-20T21:00:00+00:00")),
            "deny")

    def test_update_time_needs_offset(self):
        self.guard_session()
        self.see_event({"id": "d1", "summary": "Drive time",
                        "start": {"dateTime": "2026-10-02T08:00:00-04:00"}})
        self.assertEqual(self.pre(CAL + "update_event", {
            "eventId": "d1", "startTime": "2026-10-02T07:30:00", "notificationLevel": "NONE"}),
            "deny")

    def test_all_day_dates_allowed(self):
        self.guard_session()
        self.assertEqual(self.pre(CAL + "create_event", {
            "summary": "Travel: Tokyo", "allDay": True, "colorId": "1",
            "startTime": "2026-11-02", "endTime": "2026-11-06"}), "allow")

    # ---- never the past

    def test_create_in_past_denied(self):
        self.guard_session()
        self.assertEqual(self.pre(CAL + "create_event", {
            "summary": "Drive time", "startTime": "2026-09-30T08:00:00-04:00",
            "endTime": "2026-09-30T09:00:00-04:00"}), "deny")
        self.assertEqual(self.pre(CAL + "create_event", {
            "summary": "WFH", "allDay": True, "startTime": "2026-09-30",
            "endTime": "2026-10-01"}), "deny")
        self.assertEqual(self.pre(CAL + "create_event", {
            "summary": "WFH", "allDay": True, "startTime": "2026-10-01",
            "endTime": "2026-10-02"}), "allow")  # today in Boston still counts

    def test_update_unseen_event_denied(self):
        self.guard_session()
        self.assertEqual(self.pre(CAL + "update_event", {
            "eventId": "zz", "colorId": "2", "notificationLevel": "NONE"}), "deny")

    def test_update_on_started_event_denied_even_color(self):
        self.guard_session()
        self.see_event({"id": "old", "summary": "Deep work",
                        "start": {"dateTime": "2026-10-01T07:00:00-04:00"},
                        "end": {"dateTime": "2026-10-01T09:00:00-04:00"}})
        self.assertEqual(self.pre(CAL + "update_event", {
            "eventId": "old", "colorId": "2", "notificationLevel": "NONE"}), "deny")
        self.see_event({"id": "yday", "summary": "Travel: Paris",
                        "start": {"date": "2026-09-30"}, "end": {"date": "2026-10-02"}})
        self.assertEqual(self.pre(CAL + "update_event", {
            "eventId": "yday", "colorId": "1", "notificationLevel": "NONE"}), "deny")

    def test_update_cannot_move_into_past(self):
        self.guard_session()
        self.see_event({"id": "d2", "summary": "Drive time",
                        "start": {"dateTime": "2026-10-05T08:00:00-04:00"},
                        "end": {"dateTime": "2026-10-05T09:00:00-04:00"}})
        self.assertEqual(self.pre(CAL + "update_event", {
            "eventId": "d2", "startTime": "2026-09-29T08:00:00-04:00",
            "notificationLevel": "NONE"}), "deny")

    # ---- writes as riley@cheek.org

    RILEY = "mcp__org-connector-google_calendar__"

    def riley_config(self):
        self.env["CALENDAR_MANAGER_CONFIG_JSON"] = json.dumps({
            "calendar_id": "paul@cheek.org",
            "writer_servers": ["org-connector-google_calendar"],
            "agent_identity": "riley@cheek.org"})
        self.guard_session()

    def test_writes_only_through_riley_to_paul_by_id(self):
        self.riley_config()
        base = {"summary": "Drive time", "colorId": "1",
                "startTime": "2026-10-05T08:00:00-04:00", "endTime": "2026-10-05T09:00:00-04:00"}
        self.assertEqual(self.pre(CAL + "create_event", dict(base, calendarId="paul@cheek.org")),
                         "deny")  # Paul's own connector: not the writer
        self.assertEqual(self.pre(self.RILEY + "create_event", base), "deny")
        self.assertEqual(self.pre(self.RILEY + "create_event", dict(base, calendarId="primary")),
                         "deny")
        self.assertEqual(self.pre(self.RILEY + "create_event",
                                  dict(base, calendarId="paul@cheek.org")), "allow")
        self.assertEqual(self.pre(CAL + "list_events", {}), "allow")
        self.assertEqual(self.pre(self.RILEY + "list_events", {"calendarId": "paul@cheek.org"}),
                         "allow")

    def test_riley_created_event_is_fully_editable_after_read(self):
        self.riley_config()
        self.post(self.RILEY + "get_event", {
            "id": "f1", "summary": "Flight: BOS to LHR", "colorId": "1",
            "start": {"dateTime": "2026-10-13T18:30:00-04:00"},
            "end": {"dateTime": "2026-10-14T06:25:00+01:00"},
            "creator": {"email": "riley@cheek.org"},
            "organizer": {"email": "paul@cheek.org"},
            "attendees": [{"email": CALLIE}]})
        self.assertEqual(self.pre(self.RILEY + "update_event", {
            "eventId": "f1", "calendarId": "paul@cheek.org", "description": "BA 212, seat 3A",
            "notificationLevel": "NONE"}), "allow")
        # Same shape, but Paul made it and it has a guest: color only.
        self.post(self.RILEY + "get_event", {
            "id": "p1", "summary": "Dinner", "start": {"dateTime": "2026-10-13T18:30:00-04:00"},
            "creator": {"email": "paul@cheek.org"}, "organizer": {"email": "paul@cheek.org"},
            "attendees": [{"email": "friend@example.com"}]})
        self.assertEqual(self.pre(self.RILEY + "update_event", {
            "eventId": "p1", "calendarId": "paul@cheek.org", "description": "x",
            "notificationLevel": "NONE"}), "deny")
        self.assertEqual(self.pre(self.RILEY + "update_event", {
            "eventId": "p1", "calendarId": "paul@cheek.org", "colorId": "3",
            "notificationLevel": "NONE"}), "allow")

    def test_riley_reading_paul_event_counts_paul_as_owner(self):
        self.riley_config()
        self.post(self.RILEY + "get_event", {
            "id": "s1", "summary": "Deep work", "start": {"dateTime": "2026-10-05T07:00:00-04:00"},
            "creator": {"email": "paul@cheek.org"}, "organizer": {"email": "paul@cheek.org"},
            "attendees": [{"email": "paul@cheek.org"}]})
        self.assertEqual(self.pre(self.RILEY + "update_event", {
            "eventId": "s1", "calendarId": "paul@cheek.org", "startTime": "2026-10-05T07:30:00-04:00",
            "notificationLevel": "NONE"}), "allow")

    # ---- update

    def test_color_and_freebusy_on_guest_event_allowed(self):
        self.guard_session()
        self.see_event({"id": "g1", "summary": "1:1", "start": {"dateTime": "2026-10-05T10:00:00-04:00"},
                        "attendees": [{"email": "colleague@mit.edu"}]})
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
