'use strict';
// Run with: node tests/test_ui.cjs
// Tests use the exact production helper source, with no DOM or npm dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
const context = { state: { timezone: 'UTC' }, Intl, Date };
vm.createContext(context);
const dateHelpers = source.slice(source.indexOf('  function dateParts('), source.indexOf('  function showNotice('));
const dailyHelper = source.slice(source.indexOf('  function dailyTotals('), source.indexOf('  function renderStats('));
assert.ok(dateHelpers.length > 100 && dailyHelper.length > 100, 'Production helpers must be found');
vm.runInContext(`function finite(value) { return Number.isFinite(Number(value)) ? Number(value) : 0; }\n${dateHelpers}\n${dailyHelper}`, context);
let passed = 0;
function check(zone, input, iso) {
  context.state.timezone = zone;
  const epoch = context.inputToEpoch(input);
  assert.equal(new Date(epoch * 1000).toISOString(), iso, `${zone} converts configured wall time`);
  assert.equal(context.localInput(epoch), input, `${zone} round-trips wall time`);
  passed += 1;
}
check('Asia/Shanghai', '2026-10-01T21:00', '2026-10-01T13:00:00.000Z');
check('America/Los_Angeles', '2026-10-01T06:00', '2026-10-01T13:00:00.000Z');
check('Asia/Kathmandu', '2026-10-01T18:45', '2026-10-01T13:00:00.000Z');
check('UTC', '2026-10-01T13:00', '2026-10-01T13:00:00.000Z');
check('America/New_York', '2026-03-08T01:30', '2026-03-08T06:30:00.000Z');
check('America/New_York', '2026-03-08T03:30', '2026-03-08T07:30:00.000Z');
context.state.timezone = 'America/New_York';
assert.throws(() => context.inputToEpoch('2026-03-08T02:30'), /daylight saving time/, 'Reject nonexistent DST wall time');
passed += 1;
// For an ambiguous fall-back hour, the UI consistently uses the first occurrence.
check('America/New_York', '2026-11-01T01:30', '2026-11-01T05:30:00.000Z');
function log(start, end) { return { started_at: Date.parse(start) / 1000, ended_at: Date.parse(end) / 1000 }; }
context.state = { timezone: 'Asia/Shanghai', week: '2026-09-28', logs: [log('2026-10-01T15:30:00Z', '2026-10-01T16:30:00Z')] };
let totals = context.dailyTotals();
assert.equal(totals[3].hours, 0.5, 'Split first half before local midnight');
assert.equal(totals[4].hours, 0.5, 'Split second half after local midnight');
passed += 1;
context.state = { timezone: 'America/New_York', week: '2026-03-02', logs: [log('2026-03-08T05:00:00Z', '2026-03-09T04:00:00Z')] };
totals = context.dailyTotals();
assert.equal(totals[6].hours, 23, 'Spring DST day contains 23 hours');
passed += 1;
context.state = { timezone: 'America/New_York', week: '2026-10-26', logs: [log('2026-11-01T04:00:00Z', '2026-11-02T05:00:00Z')] };
assert.equal(context.dailyTotals()[6].hours, 25, 'Fall DST day contains 25 hours');
passed += 1;
context.state = { timezone: 'UTC', week: '2026-09-28', logs: [log('2026-09-27T23:30:00Z', '2026-09-28T00:30:00Z'), log('2026-10-04T23:30:00Z', '2026-10-05T00:30:00Z')] };
totals = context.dailyTotals();
assert.equal(totals[0].hours, 0.5, 'Clip start of week');
assert.equal(totals[6].hours, 0.5, 'Clip end of week');
assert.equal(totals.reduce((sum, day) => sum + day.hours, 0), 1, 'No time outside selected week counted');
passed += 1;
assert.equal(context.shiftDate('2026-12-28', 6), '2027-01-03', 'Week navigation crosses years');
assert.equal(context.shiftDate('2028-02-28', 1), '2028-02-29', 'Week navigation handles leap years');
passed += 1;
assert.throws(() => context.inputToEpoch('not-a-date'), /date and time/, 'Reject malformed input');
passed += 1;
context.state.timezone = 'UTC';
assert.equal(context.formattedDate(Date.parse('2026-10-01T13:00:00Z') / 1000), 'Oct 1, 13:00', 'Dates display in English');
assert.equal(context.formattedDate(Date.parse('2026-10-01T13:00:00Z') / 1000, { weekday: 'long' }), 'Thursday, Oct 1, 13:00', 'Weekdays display in English');
passed += 1;
const html = fs.readFileSync(path.join(__dirname, '../static/index.html'), 'utf8');
assert.match(html, /<html lang="en">/, 'Document declares English');
const dateFormatCalls = [...source.matchAll(/new Intl\.DateTimeFormat\('([^']+)'/g)];
assert.ok(dateFormatCalls.length >= 4, 'Find production date-format calls');
assert.ok(dateFormatCalls.every((match) => match[1] === 'en-US'), 'All date-format calls use the English locale');
assert.match(source, /toLocaleString\('en-US'/, 'Numbers use the English locale');
passed += 1;
console.log(`PASS ${passed} UI timezone/date and English locale cases (production helpers)`);
