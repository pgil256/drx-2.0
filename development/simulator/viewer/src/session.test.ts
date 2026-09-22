import { expect, test } from "vitest";
import { acceptSnapshot, readRecording } from "./session";
import type { Snapshot } from "./types";

const frame = (seq: number, session_id = "a") =>
  ({
    schema: 1,
    seq,
    sim_time: seq / 20,
    session_id,
    pose: {
      axial_inches: 0,
      horizontal_degrees: 0,
      lateral_degrees: 0,
      fit_inches: 0,
      force_lb: 0,
    },
    sensors: { a: 0, b: 0, c: 0, pressure_lb: 0, age_ms: 0 },
    gui: {},
    faults: {},
  }) as Snapshot;
test("rejects stale and cross-session state", () => {
  expect(acceptSnapshot(frame(2), frame(1))).toBe(false);
  expect(acceptSnapshot(frame(2), frame(2))).toBe(false);
  expect(acceptSnapshot(frame(2), frame(3, "b"))).toBe(false);
  expect(acceptSnapshot(frame(2), frame(3))).toBe(true);
});
test("rejects malformed or non-finite pose before rendering", () => {
  expect(acceptSnapshot(null, null)).toBe(false);
  expect(acceptSnapshot(null, { ...frame(1), pose: {} })).toBe(false);
  const invalid = frame(1);
  invalid.pose.axial_inches = Number.NaN;
  expect(acceptSnapshot(null, invalid)).toBe(false);
  expect(() =>
    readRecording(JSON.stringify({ kind: "state", value: { schema: 1 } })),
  ).toThrow();
});
test("replay ignores non-state events and duplicate snapshots", () => {
  const text = [
    { kind: "tx", value: "X" },
    { kind: "state", value: frame(1) },
    { kind: "state", value: frame(1) },
    { kind: "state", value: frame(2) },
  ]
    .map((value) => JSON.stringify(value))
    .join("\n");
  expect(readRecording(text)).toHaveLength(2);
});
