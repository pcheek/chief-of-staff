/**
 * calendar-manager working-location relay. Deploy it as riley@cheek.org.
 *
 * The only Calendar API surface the agents can reach. It runs as Riley, edits only
 * Paul's working-location entries, and refuses everything else. The key the cloud
 * environment holds can do nothing more than this file allows, even if an agent read it.
 *
 * Setup (once, signed in as riley@cheek.org):
 *   1. script.google.com > New project. Paste this file as Code.gs.
 *   2. Services (+) > Google Calendar API (v3), identifier "Calendar".
 *   3. Project Settings > Script properties:
 *        RELAY_KEY    a long random string (also goes in the cloud environment)
 *        CALENDAR_ID  paul@cheek.org
 *        TIME_ZONE    America/New_York
 *   4. Deploy > New deployment > Web app. Execute as: Me (riley@cheek.org).
 *      Who has access: Anyone. Copy the /exec URL.
 *   5. In the claude.ai/code environment: env vars CALENDAR_MANAGER_WL_RELAY_URL (the URL)
 *      and CALENDAR_MANAGER_WL_RELAY_KEY (the key); allow script.google.com and
 *      script.googleusercontent.com under Network access.
 *
 * Request: POST JSON {key, op: "list"|"set"|"add", ...}. Response: {ok, ...} or
 * {ok: false, refused|error}. Every call is logged under Executions.
 */

var ALLOWED_PATCH = ['workingLocationProperties', 'summary', 'start', 'end'];
var TYPES = {home: 'homeOffice', office: 'officeLocation', custom: 'customLocation'};

function doPost(e) {
  var req;
  try {
    req = JSON.parse(e.postData.contents);
  } catch (err) {
    return reply({ok: false, refused: 'body is not JSON'});
  }
  var props = PropertiesService.getScriptProperties();
  if (!req.key || req.key !== props.getProperty('RELAY_KEY')) {
    return reply({ok: false, refused: 'bad key'});
  }
  var cal = props.getProperty('CALENDAR_ID');
  var zone = props.getProperty('TIME_ZONE') || 'America/New_York';
  try {
    var out;
    if (req.op === 'list') out = list(cal, zone, req);
    else if (req.op === 'set') out = set(cal, zone, req);
    else if (req.op === 'add') out = add(cal, zone, req);
    else throw refusal('op must be list, set or add');
    console.log(JSON.stringify({op: req.op, eventId: req.eventId || null, ok: true}));
    return reply(Object.assign({ok: true}, out));
  } catch (err) {
    var refused = err && err.refused;
    console.log(JSON.stringify({op: req.op, eventId: req.eventId || null,
                                ok: false, why: String(err && err.message || err)}));
    return reply(refused ? {ok: false, refused: err.message}
                         : {ok: false, error: String(err && err.message || err)});
  }
}

function list(cal, zone, req) {
  var day = isoDate(req.date);
  var res = Calendar.Events.list(cal, {
    eventTypes: ['workingLocation'], singleEvents: true, orderBy: 'startTime',
    timeMin: startOfDay(day, zone), timeMax: startOfDay(addDays(day, 1), zone)
  });
  return {items: (res.items || []).map(summarize)};
}

function set(cal, zone, req) {
  if (!req.eventId) throw refusal('set needs eventId');
  var ev = Calendar.Events.get(cal, req.eventId);
  checkCurrent(ev, zone);
  var patch = {workingLocationProperties: props_(req.type, req.label),
               summary: req.type === 'home' ? 'Home' : req.label};
  if (req.start || req.end) {
    if (ev.start.date) throw refusal('an all-day entry cannot be retimed; add a partial-day one');
    patch.start = {dateTime: timed(req.start)};
    patch.end = {dateTime: timed(req.end)};
    checkFutureRange(patch.start.dateTime, patch.end.dateTime);
  }
  Object.keys(patch).forEach(function (k) {
    if (ALLOWED_PATCH.indexOf(k) < 0) throw refusal('field ' + k + ' is not allowed');
  });
  var res = Calendar.Events.patch(patch, cal, req.eventId, {sendUpdates: 'none'});
  return {updated: summarize(res)};
}

function add(cal, zone, req) {
  var body = {
    eventType: 'workingLocation', visibility: 'public', transparency: 'transparent',
    summary: req.type === 'home' ? 'Home' : req.label,
    workingLocationProperties: props_(req.type, req.label),
    extendedProperties: {private: {calendarManager: 'agent'}}
  };
  if (req.date) {
    var day = isoDate(req.date);
    if (day < today(zone)) throw refusal(day + ' is in the past');
    body.start = {date: day};
    body.end = {date: addDays(day, 1)};
  } else {
    body.start = {dateTime: timed(req.start)};
    body.end = {dateTime: timed(req.end)};
    checkFutureRange(body.start.dateTime, body.end.dateTime);
  }
  var res = Calendar.Events.insert(body, cal, {sendUpdates: 'none'});
  return {created: summarize(res)};
}

// ------------------------------------------------------------------ checks

function checkCurrent(ev, zone) {
  if (ev.eventType !== 'workingLocation') {
    throw refusal('event ' + ev.id + ' is a ' + ev.eventType + ' event, not a working location');
  }
  if (ev.start.date) {
    var lastDay = addDays(ev.end.date || ev.start.date, -1);
    if (lastDay < today(zone)) throw refusal('event ' + ev.id + ' ended on ' + lastDay);
  } else if (new Date(ev.start.dateTime) < new Date()) {
    throw refusal('event ' + ev.id + ' already started at ' + ev.start.dateTime);
  }
}

function checkFutureRange(start, end) {
  if (new Date(end) <= new Date(start)) throw refusal('end must be after start');
  if (new Date(start) < new Date()) throw refusal('start ' + start + ' is in the past');
}

function props_(type, label) {
  var t = TYPES[type];
  if (!t) throw refusal('type must be home, office or custom');
  if (type === 'home') return {type: t, homeOffice: {}};
  if (!label) throw refusal('type ' + type + ' needs a label');
  var p = {type: t};
  p[type === 'office' ? 'officeLocation' : 'customLocation'] = {label: String(label)};
  return p;
}

function timed(ts) {
  if (!ts || !/T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})$/.test(ts)) {
    throw refusal('time ' + ts + ' needs an explicit UTC offset');
  }
  return ts;
}

// ------------------------------------------------------------------ helpers

function summarize(ev) {
  var wl = ev.workingLocationProperties || {};
  var label = ((wl.customLocation || wl.officeLocation || {}).label) ||
              (wl.type === 'homeOffice' ? 'Home' : '');
  return {id: ev.id, start: ev.start, end: ev.end, type: wl.type, label: label,
          recurring: !!ev.recurringEventId,
          agent: !!(ev.extendedProperties && ev.extendedProperties.private &&
                    ev.extendedProperties.private.calendarManager === 'agent')};
}

function refusal(msg) {
  var e = new Error(msg);
  e.refused = true;
  return e;
}

function isoDate(s) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s || '')) throw refusal('date must be YYYY-MM-DD');
  return s;
}

function today(zone) {
  return Utilities.formatDate(new Date(), zone, 'yyyy-MM-dd');
}

function addDays(day, n) {
  var d = new Date(day + 'T12:00:00Z');
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function startOfDay(day, zone) {
  // RFC 3339 midnight in `zone`, offset taken from noon that day so DST days are right.
  var noon = new Date(day + 'T12:00:00Z');
  var off = Utilities.formatDate(noon, zone, 'XXX');
  return day + 'T00:00:00' + off;
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
