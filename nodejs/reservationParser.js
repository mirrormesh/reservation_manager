function hasTimeOverlap(newStart, newEnd, existStart, existEnd) {
  if (!(newStart instanceof Date) || !(newEnd instanceof Date) || !(existStart instanceof Date) || !(existEnd instanceof Date)) {
    throw new TypeError('all arguments must be Date objects');
  }
  if (newStart >= newEnd) {
    throw new Error('newStart must be earlier than newEnd');
  }
  if (existStart >= existEnd) {
    throw new Error('existStart must be earlier than existEnd');
  }

  return newStart < existEnd && newEnd > existStart;
}

function canReserve(newStart, newEnd, existingReservations) {
  if (newStart >= newEnd) {
    throw new Error('newStart must be earlier than newEnd');
  }

  return !existingReservations.some((reservation) =>
    hasTimeOverlap(newStart, newEnd, reservation.start, reservation.end)
  );
}

function floorToTenMinutes(dateValue) {
  const result = new Date(dateValue.getTime());
  result.setSeconds(0, 0);
  result.setMinutes(Math.floor(result.getMinutes() / 10) * 10);
  return result;
}

function ceilToTenMinutes(dateValue) {
  const result = new Date(dateValue.getTime());
  const hasSubMinute = result.getSeconds() > 0 || result.getMilliseconds() > 0;
  result.setSeconds(0, 0);

  const minute = result.getMinutes();
  const remainder = minute % 10;
  if (remainder === 0 && !hasSubMinute) {
    return result;
  }

  const minutesToAdd = remainder === 0 ? 10 : (10 - remainder);
  result.setMinutes(minute + minutesToAdd);
  return result;
}

function normalizeReservationRange(start, end) {
  return {
    start: floorToTenMinutes(start),
    end: ceilToTenMinutes(end),
  };
}

function extractResourceFromFragments(text, fragments) {
  let resource = text;
  for (const fragment of fragments) {
    if (fragment) {
      resource = resource.replace(fragment, ' ');
    }
  }

  resource = resource
    .replace(/[~\-]/g, ' ')
    .replace(/부터|까지/g, ' ')
    .replace(/예약(해줘|해주세요)?|잡아줘|로|을|를|에|좀|해줘/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  return resource || null;
}

function parseReservationRequest(text, options = {}) {
  if (!text || !text.trim()) {
    throw new Error('text must not be empty');
  }

  const dateMatch = text.match(/(\d{4}[/-]\d{1,2}[/-]\d{1,2})/);
  if (dateMatch) {
    const timeMatches = [...text.matchAll(/(?<!\d)((?:[01]?\d|2[0-3]):[0-5]\d)(?!\d)/g)].map((m) => m[1]);
    if (timeMatches.length < 2) {
      throw new Error('Could not find start/end time in text. Expected format: HH:MM');
    }

    const dateText = dateMatch[1].replace(/\//g, '-');
    const [startTime, endTime] = timeMatches;
    const start = new Date(`${dateText}T${startTime}:00`);
    const end = new Date(`${dateText}T${endTime}:00`);

    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
      throw new Error('Failed to parse date or time from text');
    }
    const normalized = normalizeReservationRange(start, end);

    if (normalized.start >= normalized.end) {
      throw new Error('start time must be earlier than end time');
    }

    const resource = extractResourceFromFragments(text, [dateMatch[1], startTime, endTime]);
    return { resource, start: normalized.start, end: normalized.end, rawText: text };
  }

  const dayMatch = text.match(/(오늘|내일)/);
  const meridiemTimeMatch = text.match(/(?:(오전|오후)\s*)?(\d{1,2})\s*시(?:\s*(\d{1,2})\s*분)?/);
  const durationMatch = text.match(/(\d+)\s*시간(?:\s*(\d+)\s*분)?/);
  if (!dayMatch || !meridiemTimeMatch || !durationMatch) {
    throw new Error("Could not find a date in text. Expected format: YYYY-MM-DD or relative form like '오늘 오후 5시 1시간'");
  }

  const referenceDate = options.referenceDate instanceof Date ? options.referenceDate : new Date();
  const base = new Date(referenceDate.getTime());
  base.setHours(0, 0, 0, 0);
  if (dayMatch[1] === '내일') {
    base.setDate(base.getDate() + 1);
  }

  const meridiem = meridiemTimeMatch[1];
  let hour = Number(meridiemTimeMatch[2]);
  const minute = Number(meridiemTimeMatch[3] || '0');
  if (meridiem === '오후' && hour < 12) {
    hour += 12;
  }
  if (meridiem === '오전' && hour === 12) {
    hour = 0;
  }
  if (hour > 23 || minute > 59) {
    throw new Error('Invalid hour/minute in relative time expression');
  }

  const durationHours = Number(durationMatch[1]);
  const durationMinutes = Number(durationMatch[2] || '0');
  const durationMillis = ((durationHours * 60) + durationMinutes) * 60 * 1000;
  if (durationMillis <= 0) {
    throw new Error('duration must be greater than zero');
  }

  const start = new Date(base.getTime());
  start.setHours(hour, minute, 0, 0);
  const end = new Date(start.getTime() + durationMillis);
  const normalized = normalizeReservationRange(start, end);
  if (normalized.start >= normalized.end) {
    throw new Error('start time must be earlier than end time');
  }

  const resource = extractResourceFromFragments(text, [dayMatch[0], meridiemTimeMatch[0], durationMatch[0], '오전', '오후']);
  return { resource, start: normalized.start, end: normalized.end, rawText: text };
}

function canReserveFromText(text, existingReservations) {
  const parsed = parseReservationRequest(text);
  return canReserve(parsed.start, parsed.end, existingReservations);
}

module.exports = {
  hasTimeOverlap,
  canReserve,
  parseReservationRequest,
  canReserveFromText,
  normalizeReservationRange,
};
