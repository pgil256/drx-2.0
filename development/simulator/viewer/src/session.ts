import type { Snapshot } from "./types";

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function validSnapshot(value: unknown): value is Snapshot {
  if (
    !object(value) ||
    value.schema !== 1 ||
    typeof value.session_id !== "string" ||
    !Number.isInteger(value.seq) ||
    !Number.isFinite(value.sim_time) ||
    !object(value.pose) ||
    !object(value.sensors) ||
    !object(value.gui) ||
    !object(value.faults)
  )
    return false;
  return (
    [
      "axial_inches",
      "horizontal_degrees",
      "lateral_degrees",
      "fit_inches",
      "force_lb",
    ].every((key) =>
      Number.isFinite((value.pose as Record<string, unknown>)[key]),
    ) &&
    ["a", "b", "c", "pressure_lb", "age_ms"].every((key) =>
      Number.isFinite((value.sensors as Record<string, unknown>)[key]),
    )
  );
}

export function acceptSnapshot(
  previous: Snapshot | null,
  next: unknown,
): next is Snapshot {
  return (
    validSnapshot(next) &&
    (!previous ||
      (previous.session_id === next.session_id &&
        next.seq > previous.seq &&
        next.sim_time >= previous.sim_time))
  );
}

export function readRecording(text: string): Snapshot[] {
  const frames: Snapshot[] = [];
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    const event = JSON.parse(line);
    if (event.kind === "state") {
      if (!validSnapshot(event.value))
        throw new Error("Recording contains invalid device state");
      if (frames.length && frames[0].session_id !== event.value.session_id)
        throw new Error("Recording combines different sessions");
      if (acceptSnapshot(frames.at(-1) ?? null, event.value))
        frames.push(event.value);
    }
  }
  return frames;
}
