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

function parseReservationRequest(text) {
  if (!text || !text.trim()) {
    throw new Error('text must not be empty');
  }

  const dateMatch = text.match(/(\d{4}[/-]\d{1,2}[/-]\d{1,2})/);
  if (!dateMatch) {
    throw new Error('Could not find a date in text. Expected format: YYYY-MM-DD');
  }

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

  let resource = text
    .replace(dateMatch[1], ' ')
    .replace(startTime, ' ')
    .replace(endTime, ' ')
    .replace(/[~\-]/g, ' ')
    .replace(/부터|까지/g, ' ')
    .replace(/예약(해줘|해주세요)?|잡아줘|로|을|를|에|좀|해줘/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  if (!resource) {
    resource = null;
  }

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
