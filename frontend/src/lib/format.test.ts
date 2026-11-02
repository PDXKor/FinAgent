import { formatAgo, formatCount, formatDuration, formatElapsed } from "./format";

test("formatDuration picks a compact unit", () => {
  expect(formatDuration(850)).toBe("850ms");
  expect(formatDuration(12_400)).toBe("12s");
  expect(formatDuration(185_000)).toBe("3m 05s");
  expect(formatDuration(3_720_000)).toBe("1h 02m");
});

test("formatElapsed measures open runs to now", () => {
  const start = "2026-11-01T12:00:00Z";
  expect(formatElapsed(start, "2026-11-01T12:00:05Z")).toBe("5s");
  expect(formatElapsed(start, null, Date.parse("2026-11-01T12:01:30Z"))).toBe("1m 30s");
});

test("formatAgo and formatCount handle nulls", () => {
  const now = Date.parse("2026-11-01T12:00:00Z");
  expect(formatAgo("2026-11-01T11:00:00Z", now)).toBe("1h ago");
  expect(formatAgo(null)).toBe("—");
  expect(formatCount(null)).toBe("—");
  expect(formatCount(0)).toBe("0");
});
