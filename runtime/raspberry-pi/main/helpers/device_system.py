"""Bounded Linux network, clock, audio-test and power operations."""

import array
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
import wave


def run_command(args: List[str], timeout: int = 5, input_text: Optional[str] = None) -> str:
    """Never log command output or stdin, which may contain a network secret."""
    try:
        result = subprocess.run(args, input=input_text, capture_output=True, text=True,
                                timeout=timeout, env=dict(os.environ, LC_ALL="C"))
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("The system operation is unavailable or timed out.") from None
    if result.returncode:
        raise RuntimeError("The system rejected the operation. Check device permissions.")
    return result.stdout.strip()


def escaped_fields(line: str) -> List[str]:
    """Decode nmcli terse fields without splitting escaped SSID colons."""
    fields, current, escaped = [], [], False
    for character in line:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    return fields + ["".join(current)]


class DeviceSystem:
    """Operate only installed system interfaces, never install tools or elevate privileges."""

    def __init__(self, state_dir: Path) -> None:
        self.root = state_dir

    @staticmethod
    def linux() -> None:
        if sys.platform != "linux":
            raise RuntimeError("This control is available on the Raspberry Pi.")

    @staticmethod
    def _wifi_interface() -> str:
        interfaces = [p.parent.name for p in Path("/sys/class/net").glob("*/wireless")]
        if not interfaces:
            raise RuntimeError("No Wi-Fi adapter was found.")
        return sorted(interfaces)[0]

    def network(self) -> Dict[str, Any]:
        self.linux()
        result = {"network": "No active network", "addresses": [], "wifi_backend": "Unavailable"}
        addresses = json.loads(run_command(["ip", "-j", "address", "show"]))
        result["addresses"] = [
            f"{interface['ifname']}: {address['local']}"
            for interface in addresses if interface.get("ifname") != "lo"
            for address in interface.get("addr_info", [])
            if address.get("scope") == "global"
        ]
        if shutil.which("nmcli"):
            try:
                lines = run_command(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION",
                                     "device", "status"]).splitlines()
                active = [escaped_fields(line) for line in lines]
                result["network"] = ", ".join(f"{r[0]}: {r[3]}" for r in active
                                               if len(r) == 4 and r[2] == "connected")
                result["wifi_backend"] = "NetworkManager"
                return result
            except RuntimeError:
                pass
        if shutil.which("wpa_cli"):
            try:
                state = self._wpa_status(self._wifi_interface())
                result["wifi_backend"] = "wpa_supplicant"
                if state.get("wpa_state") == "COMPLETED":
                    result["network"] = "Wi-Fi: " + state.get("ssid", "Connected")
            except RuntimeError:
                pass
        if result["addresses"] and result["network"] == "No active network":
            result["network"] = "Network interface connected"
        return result

    def test_internet(self) -> str:
        """Probe public HTTPS independently from the authenticated cloud API."""
        request = Request("https://www.raspberrypi.com/", method="HEAD")
        try:
            with urlopen(request, timeout=5) as response:
                return "Reachable over HTTPS" if response.status == 200 else "Unexpected response"
        except Exception:
            return "HTTPS check failed (offline, captive portal, or blocked test endpoint)"

    def wifi_scan(self) -> List[Dict[str, str]]:
        self.linux()
        interface = self._wifi_interface()
        if self.network()["wifi_backend"] == "NetworkManager":
            lines = run_command([
                "nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list",
                "ifname", interface, "--rescan", "yes",
            ], timeout=15).splitlines()
            rows = [escaped_fields(line) for line in lines]
            return [{"ssid": r[0], "signal": r[1] + "%", "security": r[2], "backend": "nmcli"}
                    for r in rows if len(r) == 3 and r[0]]
        run_command(["wpa_cli", "-i", interface, "scan"])
        time.sleep(1)
        rows = run_command(["wpa_cli", "-i", interface, "scan_results"]).splitlines()[1:]
        result = []
        for row in rows:
            fields = row.split("\t", 4)
            if len(fields) == 5 and fields[4]:
                result.append({"ssid": fields[4], "signal": fields[2] + " dBm",
                               "security": fields[3], "backend": "wpa_cli"})
        return result

    @staticmethod
    def _wpa_status(interface: str) -> Dict[str, str]:
        lines = run_command(["wpa_cli", "-i", interface, "status"]).splitlines()
        return dict(line.split("=", 1) for line in lines if "=" in line)

    def wifi_connect(self, ssid: str, password: str, backend: str, security: str) -> str:
        """Join personal/open Wi-Fi; keep secrets off argv and out of error messages."""
        self.linux()
        if (not isinstance(ssid, str) or not isinstance(password, str)
                or not 1 <= len(ssid.encode("utf-8")) <= 32
                or any(ord(c) < 32 for c in ssid + password)):
            raise ValueError("Enter a valid network name and password.")
        protected = any(x in security.upper() for x in ("WPA", "WEP", "PSK", "SAE", "802.1X"))
        if any(x in security.upper() for x in ("WEP", "EAP", "802.1X", "ENTERPRISE")):
            raise ValueError("This network requires administrator provisioning outside the app.")
        if protected and not (8 <= len(password) <= 63 or
                              re.fullmatch(r"[0-9a-fA-F]{64}", password)):
            raise ValueError("Enter an 8–63 character Wi-Fi password.")
        interface = self._wifi_interface()
        if backend == "nmcli":
            run_command(["nmcli", "--wait", "30", "--ask", "device", "wifi", "connect", ssid,
                         "ifname", interface], timeout=35, input_text=password + "\n")
            return "Network connected. Use Test Connection to verify internet and cloud access."
        if backend != "wpa_cli":
            raise ValueError("Scan for networks before connecting.")
        if "SAE" in security and "PSK" not in security:
            raise ValueError("This network requires a newer network manager.")
        old = self._wpa_status(interface).get("id")
        network_id = run_command(["wpa_cli", "-i", interface, "add_network"])
        if not network_id.isdigit():
            raise RuntimeError("Unable to create a Wi-Fi connection. Check system permissions.")
        try:
            commands = [f"set_network {network_id} ssid {ssid.encode('utf-8').hex()}"]
            if protected:
                psk = (password if len(password) == 64 else hashlib.pbkdf2_hmac(
                    "sha1", password.encode(), ssid.encode(), 4096, 32).hex())
                commands.append(f"set_network {network_id} psk {psk}")
            else:
                commands.append(f"set_network {network_id} key_mgmt NONE")
            output = run_command(["wpa_cli", "-i", interface],
                                 input_text="\n".join(commands + ["quit"]) + "\n")
            if "FAIL" in output or output.count("OK") < len(commands):
                raise RuntimeError("Wi-Fi configuration was rejected.")
            selected = run_command(["wpa_cli", "-i", interface, "select_network", network_id])
            if selected != "OK":
                raise RuntimeError("Wi-Fi connection could not start.")
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                status = self._wpa_status(interface)
                if status.get("wpa_state") == "COMPLETED" and status.get("id") == network_id:
                    saved = run_command(["wpa_cli", "-i", interface, "save_config"])
                    if saved != "OK":
                        return "Connected for this session; system permissions prevented saving."
                    return "Network connected and saved. Test Connection to verify cloud access."
                time.sleep(1)
            raise RuntimeError("Wi-Fi did not connect. Check the password and signal strength.")
        except Exception:
            try:
                run_command(["wpa_cli", "-i", interface, "remove_network", network_id])
            finally:
                if old and old.isdigit():
                    run_command(["wpa_cli", "-i", interface, "select_network", old])
            raise

    def clock(self) -> Dict[str, str]:
        self.linux()
        lines = run_command(["timedatectl", "show", "-p", "Timezone", "-p", "NTP",
                             "-p", "NTPSynchronized"]).splitlines()
        return dict(line.split("=", 1) for line in lines if "=" in line)

    def timezones(self) -> List[str]:
        self.linux()
        return run_command(["timedatectl", "list-timezones"]).splitlines()

    def set_timezone(self, zone: str) -> str:
        if zone not in self.timezones():
            raise ValueError("Select a supported time zone.")
        run_command(["timedatectl", "--no-ask-password", "set-timezone", zone])
        return "Time zone updated."

    def sync_clock(self) -> str:
        self.linux()
        run_command(["timedatectl", "--no-ask-password", "set-ntp", "true"])
        return "Automatic time synchronization enabled; refresh to check synchronization."

    def test_sound(self) -> str:
        self.linux()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / "sound-test.wav"
        samples = array.array("h", (int(5000 * math.sin(2 * math.pi * 440 * i / 22050))
                                    for i in range(16538)))
        if sys.byteorder != "little":
            samples.byteswap()
        with wave.open(str(path), "wb") as output:
            output.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
            output.writeframes(samples.tobytes())
        if shutil.which("paplay"):
            try:
                run_command(["paplay", str(path)])
                return "Test tone played on the default audio output."
            except RuntimeError:
                pass
        run_command(["aplay", "-q", str(path)])
        return "Test tone played on the default audio output."

    @staticmethod
    def power(action: str) -> None:
        DeviceSystem.linux()
        if action not in ("reboot", "poweroff"):
            raise ValueError("Invalid power action.")
        run_command(["systemctl", "--no-ask-password", action], timeout=10)
