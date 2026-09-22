"""Version session inputs and independently replay the deterministic core."""
import hashlib
import json
from pathlib import Path

from simulator.controller.device import SimulatedController


def source_hash(directory: Path) -> str:
    """Fingerprint Python sources, including paths, without mutable session files."""
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*.py")):
        if any(part in ("node_modules", "__pycache__", ".cache") for part in path.parts):
            continue
        digest.update(path.relative_to(directory).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def controller_hash() -> str:
    root = Path(__file__).resolve().parents[1]
    return hashlib.sha256((source_hash(root / "core")
                           + source_hash(root / "controller")).encode()).hexdigest()


def check_replay(path: Path) -> dict:
    """Compare every recorded core snapshot against seeded input replay."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    metadata = next(row["value"] for row in rows if row["kind"] == "session")
    if metadata.get("hashes", {}).get("controller") != controller_hash():
        raise ValueError("Recording requires the controller version identified in its metadata")
    device = SimulatedController(metadata["seed"], metadata["profile"])
    inputs = [row for row in rows if row["kind"] in ("tx", "gpio", "input_fault")]
    frames = [row["value"] for row in rows if row["kind"] == "state"]
    index = tick = 0
    for frame in frames:
        target_tick = round((frame["sim_time"] - 1) * 100)
        while tick < target_tick:
            while index < len(inputs) and round((inputs[index]["sim_time"] - 1) * 100) <= tick:
                event = inputs[index]
                value = event["value"]
                if event["kind"] == "tx":
                    device.receive(value)
                elif event["kind"] == "gpio":
                    device.plant.gpio[value["pin"]] = value["level"]
                elif value["name"] not in ("disconnect", "side_effect_failure", "drop_next_ack",
                                           "wrong_next_ack", "drop_status", "fragment_bytes",
                                           "pressure_notice"):
                    device.set_fault(value["name"], value["value"])
                index += 1
            device.tick()
            device.replies()
            device.events.clear()
            tick += 1
        actual = json.loads(json.dumps(device.snapshot()))
        for key, value in actual.items():
            if frame[key] != value:
                raise AssertionError(f"Replay differs at {frame['sim_time']}: {key}")
    return {"passed": True, "snapshots": len(frames), "inputs": index,
            "sim_time": device.time_s}
