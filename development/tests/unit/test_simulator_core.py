"""Behavioral checks for the coupled controller and physical/sensor model."""
import asyncio
import json

import pytest
from aiohttp import ClientSession

from simulator.controller.device import SimulatedController
from simulator.session.profile import prepare_environment
from simulator.session.recording import check_replay
from simulator.transport.server import SimulatorServer


def advance(device, seconds):
    replies = []
    for _ in range(round(seconds * 100)):
        device.tick()
        replies.extend(device.replies())
    return "".join(replies)


def send(device, command, seconds=0.3):
    device.receive(command)
    return advance(device, seconds)


def prepare(device):
    assert "Ready to Go" in send(device, "Y", 0.6)
    assert "ZEROS|0|1900" in send(device, "L5|0|1900")
    assert "CALIBRATION|SET|" in send(device, "L0-7050")
    assert "CALIBRATION|TARE|OK" in send(device, "L1|BASELINE", 1.2)


@pytest.mark.unit
def test_preparation_requires_actual_tare_and_typed_replies():
    device = SimulatedController()
    assert "TARE_REQUIRED" in send(device, "P40")
    prepare(device)
    assert device.calibrated
    replies = send(device, "P40|40", 8)
    assert "MOTION_DONE|P|40.00" in replies
    assert device.pressure == pytest.approx(40, abs=2)
    assert device.plant.force == pytest.approx(40, abs=2)
    assert 0.9 < device.plant.pose()["axial_inches"] < 1.2


@pytest.mark.unit
def test_v2_position_ack_is_correlated_and_waits_for_motion():
    device = SimulatedController()
    payload = "42:K2400"
    frame = f"#{payload}*{device._xor(payload):02X}"
    assert "DONE|42" not in send(device, frame, 0.3)
    assert "DONE|42" in advance(device, 2)
    assert device.plant.pose()["lateral_degrees"] == pytest.approx(20, abs=0.1)


@pytest.mark.unit
def test_jam_and_frozen_sensor_have_different_physical_effects():
    jam, frozen = SimulatedController(), SimulatedController()
    jam.set_fault("jam_c", True)
    frozen.set_fault("freeze_c", True)
    send(jam, "K2400", 2)
    send(frozen, "K2400", 2)
    assert jam.position_c == frozen.position_c == 1688
    assert jam.plant.position["c"] == 1688
    assert frozen.plant.position["c"] == 2400
    assert jam.b_running and frozen.b_running


@pytest.mark.unit
def test_physical_stop_releases_load_but_serial_stop_holds():
    device = SimulatedController()
    prepare(device)
    send(device, "P40|40", 8)
    before = device.plant.position["a"]
    send(device, "X", 1)
    assert device.plant.position["a"] == before
    device.set_fault("physical_stop", True)
    replies = advance(device, 5)
    assert device.plant.force < 5
    assert "RELEASED" in replies
    assert "STOP_ENGAGED" in send(device, "K2400")


@pytest.mark.unit
def test_stale_pressure_latches_fault_and_cannot_resume_by_clearing_sensor():
    device = SimulatedController()
    prepare(device)
    send(device, "P40|40", 8)
    device.set_fault("pressure_stale", True)
    assert "FAULT|PRESSURE_SENSOR_TIMEOUT" in advance(device, 1)
    device.set_fault("pressure_stale", False)
    assert "FAULT_LATCHED" in send(device, "P40|40")
    assert not any(device.plant.velocity.values())


@pytest.mark.unit
def test_tare_failure_and_wrong_identity_are_observable():
    device = SimulatedController()
    device.set_fault("identity_mismatch", True)
    assert "FIRMWARE|simulator-v1|UNKNOWN" in send(device, "T")
    device.set_fault("tare_failure", True)
    assert "TARE|REJECTED" in send(device, "L1|BASELINE", 1.2)
    assert not device.calibrated


@pytest.mark.unit
def test_delayed_replies_do_not_block_physical_stop_or_clock():
    device = SimulatedController()
    device.set_fault("delay_ms", 1000)
    assert "OK" not in send(device, "T")
    assert "OK" in advance(device, 1)


@pytest.mark.unit
def test_seeded_simulation_replays_physical_and_sensor_state():
    first, second = SimulatedController(seed=8), SimulatedController(seed=8)
    for device in (first, second):
        prepare(device)
        send(device, "P50|50", 8)
        send(device, "J500", 2)
    assert first.snapshot() == second.snapshot()


@pytest.mark.unit
def test_isolated_profile_overrides_inherited_live_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("KNEESPA_DEVICE_DIR", "C:/physical-device")
    monkeypatch.setenv("KNEESPA_CONFIG_PATH", "C:/physical-device/real.cfg")
    monkeypatch.setenv("ADMIN_PIN_HASH", "real-hash")
    env = prepare_environment(tmp_path)
    assert env["KNEESPA_DEVICE_DIR"] == str(tmp_path / "device")
    assert "ADMIN_PIN_HASH" not in env
    assert env["KNEESPA_CONFIG_PATH"].startswith(str(tmp_path))
    assert env["KNEESPA_PROTOCOL_V2"] == "1"


@pytest.mark.unit
def test_server_roundtrip_fragmentation_and_control_authorization(tmp_path):
    async def exercise():
        server = SimulatorServer(tmp_path / "session")
        manifest = await server.start()
        reader, writer = await asyncio.open_connection("127.0.0.1", server.serial_port)
        try:
            writer.write(b"T")
            await writer.drain()
            await asyncio.sleep(0.03)
            writer.write(b"\n")
            await writer.drain()
            found = False
            for _ in range(15):
                line = await asyncio.wait_for(reader.readline(), 1)
                if line.strip() == b"OK":
                    found = True
                    break
            assert found
            async with ClientSession() as client:
                url = manifest["http_url"] + "/api/fault"
                payload = {"name": "physical_stop", "value": True}
                async with client.post(url, json=payload) as response:
                    assert response.status == 403
                headers = {"X-Simulator-Token": manifest["token"]}
                async with client.post(url, json=payload, headers=headers) as response:
                    assert response.status == 200
                assert server.controller.stop_pressed
                headers["Origin"] = "https://unrelated.example"
                async with client.post(url, json=payload, headers=headers) as response:
                    assert response.status == 403
        finally:
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0.02)
            await server.close()
        records = [json.loads(line) for line in (server.directory / "session.jsonl").read_text().splitlines()]
        assert any(row["kind"] == "tx" and row["value"] == "T" for row in records)
        assert check_replay(server.directory / "session.jsonl")["passed"]
    asyncio.run(exercise())


@pytest.mark.unit
def test_pressure_increase_only_completes_at_or_above_requested_target():
    device = SimulatedController()
    prepare(device)
    replies = send(device, "P10|20", 5)
    completion = next(line for line in replies.splitlines() if line.startswith("MOTION_DONE|P"))
    assert float(completion.split("|")[-1]) >= 10
    assert device.pressure >= 10


@pytest.mark.unit
def test_selected_pressure_ceiling_and_calibrated_idle_hard_limit():
    device = SimulatedController()
    prepare(device)
    send(device, "P20|20", 5)
    device.set_fault("pressure_bias", 40)
    assert "FAULT|PRESSURE_LIMIT" in advance(device, 0.1)
    idle = SimulatedController()
    prepare(idle)
    idle.set_fault("pressure_bias", 110)
    assert "FAULT|PRESSURE_LIMIT" in advance(idle, 0.1)


@pytest.mark.unit
def test_fit_uses_one_drive_and_pi_release_stops_even_without_serial_stop():
    device = SimulatedController()
    send(device, "FF", 0.3)
    assert device.plant.fit_inches == 0  # No Pi direction/enable yet.
    device.plant.gpio.update({17: 1, 27: 1, 22: 0})
    advance(device, 1)
    assert device.plant.fit_inches == pytest.approx(0.5, abs=0.01)
    device.plant.gpio[27] = 0
    before = device.plant.fit_inches
    advance(device, 2)
    assert device.plant.fit_inches == before
    assert "DONE" in advance(device, 4)


@pytest.mark.unit
def test_heartbeat_is_an_advisory_and_motor_stall_does_not_fabricate_arrival():
    device = SimulatedController()
    device.set_fault("jam_c", True)
    replies = send(device, "K2400", 22)
    assert "WARNING: Host heartbeat lost" in replies
    assert "WARNING: Motor stalled" in replies
    assert "MOTION_DONE" not in replies
    assert device.b_running and device.fault is None
