const test = require('node:test');
const assert = require('node:assert/strict');

const {
  hasTimeOverlap,
  canReserve,
  parseReservationRequest,
  canReserveFromText,
  normalizeReservationRange,
} = require('../reservationParser');

test('hasTimeOverlap: boundary-touching does not overlap', () => {
  const existStart = new Date('2026-02-24T10:00:00');
  const existEnd = new Date('2026-02-24T11:00:00');
  const newStart = new Date('2026-02-24T11:00:00');
  const newEnd = new Date('2026-02-24T12:00:00');

  assert.equal(hasTimeOverlap(newStart, newEnd, existStart, existEnd), false);
});

test('hasTimeOverlap: partial overlap returns true', () => {
  const existStart = new Date('2026-02-24T10:00:00');
  const existEnd = new Date('2026-02-24T11:00:00');
  const newStart = new Date('2026-02-24T10:30:00');
  const newEnd = new Date('2026-02-24T11:30:00');

  assert.equal(hasTimeOverlap(newStart, newEnd, existStart, existEnd), true);
});

test('parseReservationRequest: parses Korean natural language', () => {
  const parsed = parseReservationRequest('회의실A 2026-02-24 10:00~11:00 예약');

  assert.equal(parsed.resource, '회의실A');
  assert.equal(parsed.start.toISOString(), new Date('2026-02-24T10:00:00').toISOString());
  assert.equal(parsed.end.toISOString(), new Date('2026-02-24T11:00:00').toISOString());
});

test('canReserveFromText: overlap returns false', () => {
  const existingReservations = [{
    start: new Date('2026-02-24T10:00:00'),
    end: new Date('2026-02-24T11:00:00'),
  }];

  assert.equal(
    canReserveFromText('회의실A 2026-02-24 10:30~11:30 예약', existingReservations),
    false
  );
});

test('canReserve: non-overlap returns true', () => {
  const existingReservations = [{
    start: new Date('2026-02-24T10:00:00'),
    end: new Date('2026-02-24T11:00:00'),
  }];

  assert.equal(
    canReserve(new Date('2026-02-24T11:00:00'), new Date('2026-02-24T12:00:00'), existingReservations),
    true
  );
});

test('normalizeReservationRange: floors start and ceils end to 10-minute increments', () => {
  const start = new Date('2026-02-24T10:07:00');
  const end = new Date('2026-02-24T11:01:00');
  const normalized = normalizeReservationRange(start, end);

  assert.equal(normalized.start.toISOString(), new Date('2026-02-24T10:00:00').toISOString());
  assert.equal(normalized.end.toISOString(), new Date('2026-02-24T11:10:00').toISOString());
});

test('parseReservationRequest: parses relative Korean time expression', () => {
  const parsed = parseReservationRequest('회의실1 오늘 오후 5시 1시간 예약', {
    referenceDate: new Date('2026-02-24T09:00:00'),
  });

  assert.equal(parsed.resource, '회의실1');
  assert.equal(parsed.start.toISOString(), new Date('2026-02-24T17:00:00').toISOString());
  assert.equal(parsed.end.toISOString(), new Date('2026-02-24T18:00:00').toISOString());
});
