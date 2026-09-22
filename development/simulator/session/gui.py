"""Launch the real PyQt window against an explicitly local simulated device."""
import functools
import json
import logging
import os
import queue
import sys
import threading
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import Optional
from urllib.parse import urlparse

from simulator.session.profile import prepare_environment
from simulator.session.video import configure_vlc
from simulator.transport.gpio import SimulatedGPIO


class LocalBridge:
    """Deliver GUI/GPIO observations without blocking the Qt event loop."""

    def __init__(self, manifest: dict) -> None:
        self.manifest = manifest
        self.events = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="simulator-observations", daemon=True)
        self.thread.start()

    def request(self, route: str, payload: Optional[dict] = None) -> dict:
        request = urllib.request.Request(
            self.manifest["http_url"] + "/api/" + route,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json",
                     "X-Simulator-Token": self.manifest["token"]},
        )
        # The local simulator must not be routed through an inherited proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=1) as response:
            return json.load(response)

    def post(self, route: str, payload: dict) -> None:
        self.events.put((route, payload))

    def _run(self) -> None:
        while True:
            item = self.events.get()
            try:
                if item is None:
                    return
                self.request(*item)
            except Exception:
                logging.getLogger("simulator").exception("Could not record local GUI observation")
            finally:
                self.events.task_done()

    def close(self) -> None:
        self.events.put(None)
        self.thread.join(timeout=3)


def run_gui(manifest_path: Path, capture: Optional[Path] = None,
            close_after: Optional[float] = None, verify: Optional[str] = None,
            cloud_env: Optional[Path] = None) -> int:
    """Run production controllers and screens; replace only external dependencies."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for name, scheme in (("http_url", "http"), ("serial_url", "socket")):
        parsed = urlparse(manifest[name])
        if parsed.scheme != scheme or parsed.hostname != "127.0.0.1" or not parsed.port:
            raise ValueError("Simulation endpoints must be explicit loopback URLs")
    directory = Path(manifest["directory"]).resolve()
    if directory != manifest_path.resolve().parent:
        raise ValueError("Session directory does not match manifest")
    env = prepare_environment(directory, cloud_env)
    os.environ.clear()
    os.environ.update(env)
    repo = Path(__file__).resolve().parents[3]
    main = repo / "runtime/raspberry-pi/main"
    sys.path.insert(0, str(main))
    sys.path.insert(0, str(main.parent))
    bridge = LocalBridge(manifest)
    gpio = SimulatedGPIO(bridge.post)
    rpi = ModuleType("RPi")
    rpi.GPIO = gpio
    sys.modules["RPi"], sys.modules["RPi.GPIO"] = rpi, gpio
    configure_vlc(repo)

    import serial
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication
    import kneespa
    import controllers.connection_manager as connection
    from helpers.arduino import Arduino
    from simulator.session.cloud import cloud_client_class, staff_client_class
    import controllers.patient_controller as patient_controller
    from ui.theme import apply_theme

    connection.Arduino = functools.partial(
        Arduino, transport_factory=serial.serial_for_url, port=manifest["serial_url"]
    )

    kneespa.CloudClient = cloud_client_class(bridge, external=cloud_env is not None)
    patient_controller.StaffClient = staff_client_class(bridge, external=cloud_env is not None)

    class SimulatorWindow(kneespa.KneeSpa):
        def _send_support_email(self, **payload: str) -> None:
            self.shell.support.set_delivery_state("sending", "Capturing request locally…")

            def capture_request() -> None:
                try:
                    result = bridge.request("side-effect", {"kind": "support", **payload})
                    ok = result["ok"]
                    self.support_email_result.emit(ok, "Captured in simulator session" if ok
                                                   else "Simulated delivery failure")
                except Exception:
                    self.support_email_result.emit(False, "Local capture unavailable")

            threading.Thread(target=capture_request, daemon=True).start()

    app = QApplication([sys.argv[0]])
    app.setStyle("Fusion")
    apply_theme(app)
    kneespa._install_excepthook()
    window = SimulatorWindow(debug_mode=True)
    cloud_label = ("CLOUD: " + env["KNEESPA_DEVICE_ID"] if cloud_env else "local demo cloud")
    window.setWindowTitle("KneeSpa — SIMULATION — " + cloud_label)
    window.setFixedSize(1366, 768)
    window.move(0, 0)
    window.show()
    verification = None
    if verify:
        from simulator.session.verify import GuiVerification
        if verify == "video":
            from simulator.session.verify_video import VideoVerification
            verification = VideoVerification(window, bridge, directory, verify)
        elif verify in ("ux", "ux-stops"):
            from simulator.session.verify_ux import UxStopVerification, UxVerification
            verifier = UxStopVerification if verify == "ux-stops" else UxVerification
            verification = verifier(window, bridge, directory, verify)
        else:
            verification = GuiVerification(window, bridge, directory, verify)

    def observe() -> None:
        arduino = getattr(window, "arduino", None)
        bridge.post("gui", {
            "state": window.protocol_state,
            "initialized": bool(window.initial_setup_complete),
            "baseline_valid": bool(arduino and arduino.baseline_valid),
            "connected": bool(arduino and arduino.connected),
            "resetting": bool(window.reset_in_progress),
            "cloud_mode": "dashboard" if cloud_env else "local",
        })
        if capture:
            capture.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(capture))

    timer = QTimer(window)
    timer.timeout.connect(observe)
    timer.start(500)
    cloud_timer = QTimer(window)
    if cloud_env:
        # Refresh authenticated contact while the simulator is open. The dashboard
        # labels this as estimated connectivity; no hardware telemetry is claimed.
        cloud_timer.timeout.connect(window.cloud_client.ping_async)
        cloud_timer.start(60_000)
    if close_after:
        def finish_verification() -> None:
            for dialog in app.topLevelWidgets():
                if dialog is not window:
                    dialog.close()
            window.close()
        QTimer.singleShot(int(close_after * 1000), finish_verification)
    app.exec_()
    timer.stop()
    cloud_timer.stop()
    bridge.close()
    logging.shutdown()
    if window.restart_requested:
        return 75
    if verification and not verification.passed:
        return 1
    return 0
