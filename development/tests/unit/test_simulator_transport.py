"""Exercise wire corruption and local delivery boundaries on a real TCP stream."""
import asyncio
from uuid import uuid4

from aiohttp import ClientSession
import pytest

from simulator.transport.server import SimulatorServer
from simulator.session.recording import check_replay


@pytest.mark.unit
def test_completion_faults_fragmentation_and_local_cloud(tmp_path):
    async def exercise():
        server = SimulatorServer(tmp_path / "wire")
        manifest = await server.start()
        headers = {"X-Simulator-Token": manifest["token"]}
        reader, writer = await asyncio.open_connection("127.0.0.1", server.serial_port)
        async with ClientSession(headers=headers) as client:
            async def post(route, payload):
                async with client.post(manifest["http_url"] + "/api/" + route,
                                       json=payload) as response:
                    assert response.status == 200
                    return await response.json()

            def command(sequence):
                body = f"{sequence}:K1688"
                writer.write(f"#{body}*{server.controller._xor(body):02X}\n".encode())

            async def collect():
                lines = []
                deadline = asyncio.get_running_loop().time() + 0.65
                while asyncio.get_running_loop().time() < deadline:
                    try:
                        line = await asyncio.wait_for(reader.readline(), 0.1)
                        lines.append(line.decode().strip())
                    except asyncio.TimeoutError:
                        pass
                return lines

            try:
                await post("fault", {"name": "drop_next_ack", "value": True})
                command(41)
                lines = await collect()
                assert any(line.startswith("MOTION_DONE|K") for line in lines)
                assert "DONE|41" not in lines
                await post("fault", {"name": "wrong_next_ack", "value": True})
                command(42)
                lines = await collect()
                assert "DONE|100042" in lines and "DONE|42" not in lines
                await post("fault", {"name": "fragment_bytes", "value": 3})
                command(43)
                assert "DONE|43" in await collect()
                await post("fault", {"name": "pressure_notice", "value": True})
                notices = await collect()
                assert any(line.startswith("NOTICE|PRESSURE_NO_PROGRESS|2150|0.5|")
                           for line in notices)
                receipt_id = str(uuid4())
                response = await post("cloud", {"method": "POST",
                    "path": "/api/v1/device/treatments", "body": {"client_record_id": receipt_id}})
                assert response["client_record_id"] == receipt_id
                await post("fault", {"name": "side_effect_failure", "value": True})
                assert (await post("side-effect", {"kind": "support"}))["ok"] is False
            finally:
                writer.close()
                await writer.wait_closed()
                await server.close()
        assert check_replay(server.directory / "session.jsonl")["passed"]
    asyncio.run(exercise())


@pytest.mark.unit
def test_staff_registration_edit_and_automatic_upload_in_local_simulator(tmp_path):
    from types import SimpleNamespace
    from simulator.session.cloud import cloud_client_class, staff_client_class
    from simulator.session.gui import LocalBridge
    from helpers.patient_registration import PatientRegistration

    async def exercise():
        server = SimulatorServer(tmp_path / "patients")
        manifest = await server.start()
        bridge = SimpleNamespace(manifest=manifest)
        bridge.request = lambda route, body=None: LocalBridge.request(bridge, route, body)

        def run_workflow():
            device = cloud_client_class(bridge)()
            staff = staff_client_class(bridge)(manifest["http_url"])
            try:
                context = staff.login("staff@example.test", "simulator")
                staff.select_clinic(context["clinics"][0]["id"])
                flow = PatientRegistration(staff, device)
                draft = {"patient_id": str(uuid4()), "display_name": "Synthetic Intake", "settings": {
                    "protocol_number": 4, "duration_min": 12, "max_pressure_lb": 40,
                    "max_left_deg": 10, "max_right_deg": 10, "pulse_rate_hz": 2.4,
                }}
                patient = flow.save(draft, approve=True)
                assert patient["patient_id"] != draft["patient_id"]
                editing = PatientRegistration(staff, device, patient)
                editing.load()
                edited = editing.save(dict(patient, display_name="Edited Synthetic Intake"))
                assert edited["display_name"] == "Edited Synthetic Intake"
                record = {"client_record_id": str(uuid4()), "patient_id": patient["patient_id"]}
                queue = tmp_path / "pending.json"
                device.post_treatment_async(record, str(queue)).result(timeout=3)
                assert queue.read_text() == "[]"
                staff.logout()
            finally:
                device.close(wait=True)

        try:
            await asyncio.to_thread(run_workflow)
        finally:
            await server.close()
        recording = (server.directory / "session.jsonl").read_text()
        assert "staff@example.test" not in recording
        assert "Synthetic Intake" not in recording
    asyncio.run(exercise())
