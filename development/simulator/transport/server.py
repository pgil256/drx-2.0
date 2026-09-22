"""Local serial byte stream, viewer API, and deterministic session recording."""
import asyncio
import hashlib
import json
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4
from urllib.parse import parse_qs, urlsplit

from aiohttp import web

from simulator.controller.device import SimulatedController
from simulator.session.recording import controller_hash, source_hash


VIEWER_DIR = Path(__file__).resolve().parents[1] / "viewer" / "dist"


class SimulatorServer:
    """Own one controller and its connections within a single asyncio loop."""

    def __init__(self, directory: Path, seed: int = 1) -> None:
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.controller = SimulatedController(seed)
        self.seed = seed
        self.session_id = self.directory.name
        self.token = secrets.token_urlsafe(24)
        self.serial_writer: Optional[asyncio.StreamWriter] = None
        self.sockets = {}
        self._serial_tasks = set()
        self._serial_output = None
        self.sequence = 0
        self.http_port = 0
        self.serial_port = 0
        self.gui_state: dict = {}
        self.running = False
        self._log = (self.directory / "session.jsonl").open("w", encoding="utf-8")
        self._disconnect_until = 0.0
        self._runner = None
        self._serial_server = None
        self._ticker = None
        self._actions = []
        self.side_effect_result = "success"
        self._staff_sessions = {}
        self._clinic_id = "342a051f-97db-4023-8c13-9a161a4d17d0"
        self._patients = {"b78a9d20-853c-4d2f-b75f-3918f3d1bec3": {
            "patient_id": "b78a9d20-853c-4d2f-b75f-3918f3d1bec3",
            "display_name": "Simulator test patient", "external_ref": "DEMO",
            "pin": "2468", "version": 1,
            "settings": {"protocol_number": 1, "duration_min": 5, "max_pressure_lb": 20,
                         "max_left_deg": 10, "max_right_deg": 10, "pulse_rate_hz": 2},
        }}
        self.link_faults = {"drop_next_ack": False, "wrong_next_ack": False,
                            "drop_status": False, "fragment_bytes": 0}

    def record(self, kind: str, value: object) -> None:
        self._log.write(json.dumps({"kind": kind, "sim_time": self.controller.time_s,
                                    "wall_time": time.time(), "value": value}) + "\n")

    def snapshot(self) -> dict:
        state = self.controller.snapshot()
        state.update(schema=1, session_id=self.session_id, seq=self.sequence,
                     wall_time=time.time(), serial_connected=self.serial_writer is not None,
                     gui=self.gui_state, recording=str(self.directory),
                     model_hash=self.model_hash)
        state.update(link_faults=dict(self.link_faults),
                     local_deliveries_failed=self.side_effect_result == "failure")
        return state

    async def start(self) -> dict:
        """Bind ephemeral loopback ports before exposing the ready manifest."""
        model = VIEWER_DIR / "models/drx.glb"
        self.model_hash = hashlib.sha256(model.read_bytes()).hexdigest() if model.exists() else None
        self._serial_server = await asyncio.start_server(self._serial_client, "127.0.0.1", 0,
                                                         limit=4096)
        self.serial_port = self._serial_server.sockets[0].getsockname()[1]
        app = web.Application(client_max_size=32768, middlewares=[self._local_only])
        app.add_routes([
            web.get("/api/health", self._health), web.get("/api/state", self._state),
            web.get("/api/stream", self._stream), web.post("/api/fault", self._fault),
            web.post("/api/gpio", self._gpio), web.post("/api/gui", self._gui),
            web.post("/api/side-effect", self._side_effect),
            web.post("/api/cloud", self._cloud),
            web.post("/api/staff", self._staff),
            web.get("/api/recording", self._recording),
            web.get("/{path:.*}", self._static),
        ])
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.http_port = site._server.sockets[0].getsockname()[1]
        manifest = {"schema": 1, "session_id": self.session_id, "token": self.token,
                    "http_url": f"http://127.0.0.1:{self.http_port}",
                    "serial_url": f"socket://127.0.0.1:{self.serial_port}",
                    "directory": str(self.directory), "seed": self.seed,
                    "model_hash": self.model_hash, "backend": "emulated"}
        root = Path(__file__).resolve().parents[3]
        profile = self.controller.plant.profile
        manifest.update(profile=profile, hashes={
            "controller": controller_hash(),
            "application": source_hash(root / "runtime/raspberry-pi/main"),
            "profile": hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest(),
            "model": self.model_hash,
        })
        (self.directory / "session.json").write_text(json.dumps(manifest, indent=2),
                                                     encoding="utf-8")
        self.record("session", {key: val for key, val in manifest.items() if key != "token"})
        self.running = True
        self._ticker = asyncio.create_task(self._tick())
        return manifest

    @web.middleware
    async def _local_only(self, request: web.Request, handler: object) -> web.StreamResponse:
        expected_host = f"127.0.0.1:{self.http_port}"
        if request.host != expected_host:
            raise web.HTTPForbidden(text="Local simulator host required")
        origin = request.headers.get("Origin")
        if origin and origin != f"http://{expected_host}":
            raise web.HTTPForbidden(text="Local simulator origin required")
        if request.path.startswith("/api/") and request.path != "/api/health":
            token = request.headers.get("X-Simulator-Token", request.query.get("token", ""))
            if not secrets.compare_digest(token, self.token):
                raise web.HTTPForbidden(text="This session requires its local token")
        return await handler(request)

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({"ready": self.running, "session_id": self.session_id,
                                  "model_hash": self.model_hash})

    async def _state(self, request: web.Request) -> web.Response:
        return web.json_response(self.snapshot())

    async def _stream(self, request: web.Request) -> web.WebSocketResponse:
        socket = web.WebSocketResponse(heartbeat=15, max_msg_size=4096)
        await socket.prepare(request)
        queue = asyncio.Queue(maxsize=1)
        self.sockets[socket] = queue

        async def deliver() -> None:
            try:
                while self.running:
                    state = await queue.get()
                    await asyncio.wait_for(socket.send_json(state), 2)
            except (ConnectionError, asyncio.TimeoutError):
                await socket.close()

        sender = asyncio.create_task(deliver())
        try:
            await socket.send_json(self.snapshot())
            async for _ in socket:
                pass
        finally:
            self.sockets.pop(socket, None)
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        return socket

    async def _fault(self, request: web.Request) -> web.Response:
        payload = await request.json()
        name, value = payload.get("name"), payload.get("value")
        try:
            if name == "disconnect":
                if isinstance(value, bool) or not isinstance(value, (float, int)):
                    raise ValueError("Disconnect duration must be numeric")
                if not 0 <= value <= 120:
                    raise ValueError("Disconnect duration must be 0–120 seconds")
                self._disconnect_until = self.controller.time_s + value
                if self.serial_writer:
                    self.serial_writer.close()
                self.record("fault", payload)
            elif name == "side_effect_failure":
                if not isinstance(value, bool):
                    raise ValueError("Expected boolean")
                self.side_effect_result = "failure" if value else "success"
                self.record("fault", payload)
            elif name == "pressure_notice":
                # Explicit wire fixture, not a prediction of the synthetic plant.
                # Exercise the real parser and advisory UI without changing load.
                if value is not True:
                    raise ValueError("Pressure notice requires true")
                if self._serial_output is None:
                    raise web.HTTPConflict(text="Connect the simulated GUI first")
                data = ("NOTICE|PRESSURE_NO_PROGRESS|2150|0.5|"
                        f"{max(0.0, self.controller.pressure):.3f}\n")
                try:
                    self._serial_output.put_nowait(data.encode("ascii"))
                except asyncio.QueueFull:
                    raise web.HTTPServiceUnavailable(text="Simulated serial output is full")
                self.record("rx", data.rstrip())
            elif name in self.link_faults:
                if name == "fragment_bytes":
                    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 64:
                        raise ValueError("Fragment size must be an integer from 0 to 64")
                elif not isinstance(value, bool):
                    raise ValueError("Expected boolean")
                self.link_faults[name] = value
            else:
                self.controller.set_fault(name, value)
        except (ValueError, TypeError) as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        self.record("input_fault", payload)
        return web.json_response({"ok": True})

    async def _gpio(self, request: web.Request) -> web.Response:
        payload = await request.json()
        pin, level = payload.get("pin"), payload.get("level")
        if not isinstance(pin, int) or not 0 <= pin <= 69 or level not in (0, 1):
            raise web.HTTPBadRequest(text="Invalid GPIO output")
        self.controller.plant.gpio[pin] = level
        self.record("gpio", payload)
        # The fixture couples these outputs to the single FIT motor at its next tick.
        return web.json_response({"ok": True})

    async def _gui(self, request: web.Request) -> web.Response:
        state = await request.json()
        if not isinstance(state, dict):
            raise web.HTTPBadRequest(text="GUI state must be an object")
        if state != self.gui_state:
            self.gui_state = state
            self.record("gui", state)
        return web.json_response({"ok": True})

    async def _side_effect(self, request: web.Request) -> web.Response:
        payload = await request.json()
        self.record("local_side_effect", payload)
        return web.json_response({"ok": self.side_effect_result == "success"})

    async def _cloud(self, request: web.Request) -> web.Response:
        """Capture the real cloud client's requests and return a local fixture reply."""
        payload = await request.json()
        method, path, body = payload.get("method"), payload.get("path"), payload.get("body")
        self.record("local_side_effect", {"kind": "cloud", "method": method, "path": path,
                                          "body": None if path.endswith("/lookup") else body})
        if self.side_effect_result == "failure":
            return web.json_response({"error": "unavailable", "retryable": True})
        now = datetime.now(timezone.utc).isoformat()
        if method == "GET" and path == "/api/v1/device/ping":
            result = {"device_name": "Local simulator", "server_time": now,
                      "min_app_version": "0.0.0"}
        elif method == "POST" and path == "/api/v1/device/patients/lookup":
            result = next((patient for patient in self._patients.values()
                           if isinstance(body, dict) and patient["pin"] == body.get("pin")), None)
            if result is None:
                return web.json_response({"error": "unknown_pin", "retryable": False})
        elif method == "POST" and path == "/api/v1/device/treatments":
            if not isinstance(body, dict) or "client_record_id" not in body:
                raise web.HTTPBadRequest(text="Missing client record ID")
            result = {"id": str(uuid4()), "client_record_id": body["client_record_id"],
                      "received_at": now}
        else:
            raise web.HTTPNotFound(text="Unsupported local cloud operation")
        return web.json_response(dict(result, _http_status=200))

    async def _staff(self, request: web.Request) -> web.Response:
        """Synthetic staff API; no credentials or patient bodies enter the recording."""
        payload = await request.json()
        method, raw_path = payload["method"], payload["path"]
        path = urlsplit(raw_path).path
        body = payload.get("body") or {}
        session_id = payload["session"]
        if self.side_effect_result == "failure":
            return web.json_response({"error": "unavailable", "uncertain": method != "GET"})
        clinic = {"id": self._clinic_id, "name": "Simulator clinic"}
        if path == "/login" and method == "POST":
            if body != {"email": "staff@example.test", "password": "simulator"}:
                return web.json_response({"error": "invalid_credentials"})
            self._staff_sessions[session_id] = {"selected": False}
            return web.json_response({"ok": True, "mfa_required": False})
        if path == "/logout":
            self._staff_sessions.pop(session_id, None)
            return web.json_response({"ok": True})
        session = self._staff_sessions.get(session_id)
        if session is None:
            return web.json_response({"error": "not_authenticated"})
        if path == "/me":
            return web.json_response({"email": "staff@example.test", "clinics": [clinic],
                "clinic": clinic if session["selected"] else None,
                "permissions": ["patients.edit", "plans.approve", "patients.pin.view"]})
        if path == "/clinic/select":
            if body.get("site_id") != self._clinic_id:
                return web.json_response({"error": "not_found"})
            session["selected"] = True
            return web.json_response({"ok": True, "clinic_id": self._clinic_id})
        if not session["selected"]:
            return web.json_response({"error": "no_clinic_access"})
        if path == "/patients" and method == "POST":
            identity = str(uuid4())
            used = {patient["pin"] for patient in self._patients.values()}
            pin = next(f"{n:04d}" for n in range(10000) if f"{n:04d}" not in used)
            settings = {key: body[key] for key in (
                "protocol_number", "duration_min", "max_pressure_lb", "max_left_deg",
                "max_right_deg", "pulse_rate_hz",
            )}
            approved = body.get("approve_initial_plan", False)
            plan = {"id": str(uuid4()), "settings": settings} if approved else None
            self._patients[identity] = {"patient_id": identity, "display_name": body["display_name"],
                "external_ref": None, "version": 1, "pin": pin, "settings": settings, "plan": plan}
            return web.json_response({"id": identity, "pin": pin, "external_ref": None,
                                      "plan_approved": approved})
        if path == "/patients" and method == "GET":
            query = parse_qs(urlsplit(raw_path).query)
            term = query.get("q", [""])[0].lower()
            items = [{"id": p["patient_id"], "display_name": p["display_name"], "pin": p["pin"],
                      "status": "active", "external_ref": p.get("external_ref")}
                     for p in self._patients.values() if term in p["display_name"].lower()]
            page = max(1, int(query.get("page", [1])[0]))
            return web.json_response({"items": items[(page - 1) * 25:page * 25], "total": len(items),
                                      "page": page, "pages": max(1, (len(items) + 24) // 25)})
        parts = path.strip("/").split("/")
        patient = self._patients.get(parts[1]) if len(parts) >= 2 else None
        if patient is None:
            return web.json_response({"error": "not_found"})
        if len(parts) == 2 and method == "GET":
            return web.json_response({"id": patient["patient_id"], "status": "active",
                "display_name": patient["display_name"], "version": patient["version"],
                "current_settings": patient["settings"], "plan": {"current": patient.get("plan")}})
        if len(parts) == 2 and method == "PATCH":
            if body.get("expected_version") != patient["version"]:
                return web.json_response({"error": "stale_update"})
            patient.update(display_name=body["display_name"], version=patient["version"] + 1)
            return web.json_response({"ok": True, "version": patient["version"]})
        if len(parts) == 3 and parts[2] == "plan" and method == "POST":
            current = patient.get("plan") or {}
            if body.get("expected_current_revision_id") != current.get("id"):
                return web.json_response({"error": "stale_plan"})
            settings = {key: body[key] for key in patient["settings"]}
            patient["plan"] = {"id": str(uuid4()), "settings": settings}
            patient["settings"] = settings
            return web.json_response(patient["plan"])
        return web.json_response({"error": "not_found"})

    async def _recording(self, request: web.Request) -> web.Response:
        self._log.flush()
        return web.FileResponse(self.directory / "session.jsonl",
                                headers={"Content-Disposition": 'attachment; filename="session.jsonl"'})

    async def _static(self, request: web.Request) -> web.Response:
        relative = request.match_info["path"] or "index.html"
        target = (VIEWER_DIR / relative).resolve()
        if not target.is_relative_to(VIEWER_DIR.resolve()) or not target.is_file():
            raise web.HTTPNotFound(text="Viewer asset missing. Build development/simulator/viewer.")
        return web.FileResponse(target)

    async def _serial_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter) -> None:
        if self.serial_writer or self.controller.time_s < self._disconnect_until:
            writer.close()
            await writer.wait_closed()
            return
        self.serial_writer = writer
        task = asyncio.current_task()
        self._serial_tasks.add(task)
        queue = asyncio.Queue(maxsize=2048)
        self._serial_output = queue

        async def deliver() -> None:
            try:
                while self.running:
                    data = await queue.get()
                    size = self.link_faults["fragment_bytes"] or len(data)
                    for start in range(0, len(data), size):
                        writer.write(data[start:start + size])
                        await asyncio.wait_for(writer.drain(), 1)
                        if size < len(data):
                            await asyncio.sleep(0.002)
            except (ConnectionError, asyncio.TimeoutError):
                writer.close()

        sender = asyncio.create_task(deliver())
        self.record("serial_connection", True)
        try:
            while self.running:
                data = await reader.readline()
                if not data:
                    break
                raw = data.decode("ascii", errors="replace").strip()
                self.record("tx", raw)
                self.controller.receive(raw)
        except (ConnectionError, ValueError):
            pass
        finally:
            if self.serial_writer is writer:
                self.serial_writer = None
                self._serial_output = None
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.record("serial_connection", False)
            self._serial_tasks.discard(task)

    async def _tick(self) -> None:
        deadline = time.monotonic()
        last_snapshot = self.controller.time_s
        while self.running:
            deadline += 0.01
            self.controller.tick()
            for event in self.controller.events:
                self.record("fault", event)
            self.controller.events.clear()
            for data in self.controller.replies():
                if (self.link_faults["drop_status"] and data.startswith(("STATUS_START", "DIAG|"))
                        or self.link_faults["drop_next_ack"] and data.startswith("DONE")):
                    if data.startswith("DONE"):
                        self.link_faults["drop_next_ack"] = False
                    self.record("dropped_rx", data.rstrip())
                    continue
                if self.link_faults["wrong_next_ack"] and data.startswith("DONE|"):
                    self.record("controller_rx", data.rstrip())
                    data = "DONE|" + str(int(data.split("|")[1]) + 100000) + "\n"
                    self.link_faults["wrong_next_ack"] = False
                self.record("rx", data.rstrip())
                if self.serial_writer:
                    try:
                        self._serial_output.put_nowait(data.encode("ascii"))
                    except asyncio.QueueFull:
                        self.serial_writer.close()
            if self.controller.time_s - last_snapshot >= 0.05:
                self.sequence += 1
                state = self.snapshot()
                self.record("state", state)
                self._log.flush()
                for queue in self.sockets.values():
                    if queue.full():
                        queue.get_nowait()
                    queue.put_nowait(state)
                last_snapshot = self.controller.time_s
            await asyncio.sleep(max(0, deadline - time.monotonic()))

    async def close(self) -> None:
        """Close only this session's endpoints and finish its record."""
        self.running = False
        if self._ticker:
            await self._ticker
        if self.serial_writer:
            self.serial_writer.close()
        for socket in list(self.sockets):
            await socket.close()
        if self._serial_server:
            self._serial_server.close()
            await self._serial_server.wait_closed()
        if self._serial_tasks:
            await asyncio.gather(*self._serial_tasks, return_exceptions=True)
        if self._runner:
            await self._runner.cleanup()
        self.record("closed", self.snapshot())
        self._log.close()
