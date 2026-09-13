#!/usr/bin/env python3
"""
Lateral-pot probe: reproduce the "lateral 4085 during a live axial move"
symptom with NO GUI involved, and print a verdict.

Modes (run on the Pi with the KneeSpa app NOT running):

    python3 tools/lateral_pot_probe.py                 # rest, I12 move out, home
    python3 tools/lateral_pot_probe.py --pressure 10   # rest, tare, P10 (the
                                                       #   exact protocol-1
                                                       #   condition), stop, home
    python3 tools/lateral_pot_probe.py --pressure 10 --gpio
                                                       # same, with the Pi GPIO
                                                       #   lines driven exactly
                                                       #   as the app drives them
    python3 tools/lateral_pot_probe.py --watch 30      # watch only, no motion
    python3 tools/lateral_pot_probe.py --stop          # just send X and exit
    python3 tools/lateral_pot_probe.py --banner /dev/ttyACM0
                                                       # reset the Mega over its
                                                       #   USB port and print the
                                                       #   boot banner (firmware
                                                       #   VERSION)

Safety: X is sent at start (clears any move a previous session left
running), whenever a commanded move does not acknowledge in time, and on
Ctrl+C or any error. A pressure move is capped at --pressure-seconds and
then stopped with X, because the firmware's own 30 s bound is advisory.

Every raw serial line is timestamped on screen and in the log file.
"""

import argparse
import os
import subprocess
import sys
import threading
import time
from datetime import datetime

try:
    import serial
except ImportError:
    print("pyserial is not installed for this python3 (the app needs it too).")
    print("Install with: pip3 install pyserial")
    sys.exit(1)

DEFAULT_PORT = "/dev/serial0"
BAUD = 115200
MOVE_TIMEOUT_S = 35.0  # firmware stall warning fires at 20 s; leave margin
LATERAL_BAND = (450, 2450)  # what the app flags (CMarks 500-2400 +/- 50)
OUT_OF_BAND_TAG = "   <<< LATERAL OUT OF BAND"
NOTICE_TAG = "   <<< FIRMWARE NOTICE"
PHASES = ("rest", "move", "hold", "tare", "pressure", "home", "watch")


class Probe:
    def __init__(self, port, log_path, c_band):
        self.ser = serial.Serial(port, BAUD, timeout=0.2, write_timeout=1)
        self.log = open(log_path, "a", encoding="utf-8")
        self.c_band = c_band
        self.lock = threading.Lock()
        self.frames = []          # (t, phase, a, b, c, p)
        self.phase = "idle"
        self.ack = threading.Event()
        self.ack_text = ""
        self.notices = []         # (t, phase, line) for WARNING/ERROR lines
        self.incomplete = []      # commands that never acknowledged
        self.running = True
        self.t0 = time.monotonic()
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    # -- output -----------------------------------------------------------
    def _out(self, text):
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = "[{}] {}".format(stamp, text)
        print(line, flush=True)
        self.log.write(line + "\n")
        self.log.flush()

    # -- serial -----------------------------------------------------------
    def send(self, cmd):
        self._out("TX " + cmd)
        self.ser.write((cmd + "\n").encode())
        self.ser.flush()

    def flush_firmware_buffer(self):
        """A bare newline terminates any half-typed command left in the
        firmware's buffer (e.g. from a minicom session), which otherwise
        swallows the first real command we send."""
        self.ser.write(b"\n")
        self.ser.flush()
        time.sleep(0.2)

    def _reader(self):
        while self.running:
            try:
                raw = self.ser.readline()
            except Exception as exc:  # port vanished etc.
                self._out("!! read error: {}".format(exc))
                return
            if not raw:
                continue
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            self._handle(line)

    def _handle(self, line):
        tag = ""
        if line.startswith("STATUS_START|") and "|STATUS_END" in line:
            body = line.split("|STATUS_END")[0].replace("STATUS_START|", "")
            tok = body.split("|")
            if tok[0] == "S" and len(tok) >= 5:
                try:
                    a, b, c = int(tok[1]), int(tok[2]), int(tok[3])
                    p = float(tok[4])
                except ValueError:
                    self._out("RX (unparseable) " + line)
                    return
                with self.lock:
                    self.frames.append((time.monotonic() - self.t0, self.phase, a, b, c, p))
                lo, hi = self.c_band
                if c < lo or c > hi:
                    tag = OUT_OF_BAND_TAG
                # Ack so the firmware keeps streaming and its heartbeat stays fed
                try:
                    self.ser.write(b"Q\n")
                except Exception:
                    pass
        elif line.startswith(("DONE", "BUSY", "OK", "ERR")):
            self.ack_text = line
            self.ack.set()
            if line.startswith("ERR"):
                self.notices.append((time.monotonic() - self.t0, self.phase, line))
        elif line.startswith("WARNING"):
            self.notices.append((time.monotonic() - self.t0, self.phase, line))
            tag = NOTICE_TAG
        elif "Ready to Go" in line:
            self.notices.append((time.monotonic() - self.t0, self.phase, "FIRMWARE RESTARTED: " + line))
            tag = NOTICE_TAG
        self._out("RX " + line + tag)

    # -- phases -----------------------------------------------------------
    def set_phase(self, name):
        with self.lock:
            self.phase = name
        self._out("--- phase: {} ---".format(name))

    def wait_ack(self, timeout):
        """Wait for DONE/BUSY/ERR after a command. Returns the ack text or ''."""
        if self.ack.wait(timeout):
            return self.ack_text
        return ""

    def command(self, cmd, timeout):
        self.ack.clear()
        self.ack_text = ""
        self.send(cmd)
        text = self.wait_ack(timeout)
        if not text:
            self._out("!! no acknowledgement for {} within {:.0f}s".format(cmd, timeout))
        return text

    def motion(self, cmd, timeout):
        """Send a motion command; if it does not complete, stop the device."""
        text = self.command(cmd, timeout)
        if not text.startswith("DONE"):
            self.incomplete.append((cmd, text or "no ack"))
            self._out("!! {} did not complete ({}); sending X".format(cmd, text or "no ack"))
            self.command("X", 3.0)
            time.sleep(1.0)
        return text

    def stop(self):
        try:
            self.command("X", 3.0)
            time.sleep(0.5)
            self.command("HF0", 3.0)
        except Exception:
            pass

    def close(self):
        self.running = False
        self.thread.join(timeout=1)
        try:
            self.ser.close()
        finally:
            self.log.close()

    # -- summary ----------------------------------------------------------
    def summary(self):
        with self.lock:
            frames = list(self.frames)
        lo, hi = self.c_band
        print()
        print("=" * 64)
        print("SUMMARY")
        print("=" * 64)
        for phase in PHASES:
            rows = [f for f in frames if f[1] == phase]
            if not rows:
                continue
            a_vals = [f[2] for f in rows]
            b_vals = [f[3] for f in rows]
            c_vals = [f[4] for f in rows]
            p_vals = [f[5] for f in rows]
            bad = [f for f in rows if f[4] < lo or f[4] > hi]
            print("{:>8}: {:3d} frames | axial A {}..{} | horiz B {}..{} | lateral C {}..{}"
                  " | pressure {:.1f}..{:.1f} lbs | C out of band: {}".format(
                      phase, len(rows), min(a_vals), max(a_vals), min(b_vals), max(b_vals),
                      min(c_vals), max(c_vals), min(p_vals), max(p_vals), len(bad)))
            if bad:
                first = bad[0]
                start = rows[0][0]
                print("          first out-of-band frame {:.1f}s into {}: C={} (A was {})".format(
                    first[0] - start, phase, first[4], first[2]))
        if self.notices:
            print("firmware notices:")
            for t, phase, line in self.notices:
                print("   [{}] {}".format(phase, line))
        if self.incomplete:
            print("moves that did not complete (X was sent):")
            for cmd, why in self.incomplete:
                print("   {} -> {}".format(cmd, why))
        print("-" * 64)

        rest = [f for f in frames if f[1] == "rest"]
        driven = [f for f in frames if f[1] in ("move", "pressure")]
        if driven:
            a_travel = max(f[2] for f in driven) - min(f[2] for f in driven)
            c_bad = [f for f in driven if f[4] < lo or f[4] > hi]
            c_span = max(f[4] for f in driven) - min(f[4] for f in driven)
            if a_travel < 50:
                print("VERDICT: the axial position barely changed while it was commanded.")
                print("         The axial motor is not moving under drive. That alone")
                print("         explains protocol 1 timing out at 0 lbs.")
            else:
                print("VERDICT: axial moved {} counts while driven.".format(a_travel))
            if c_bad:
                print("VERDICT: lateral (14) left its band while SMC 12 was driving.")
                print("         Reproduced with no GUI involved -> hardware: check the")
                print("         lateral pot ground/wiper lead and where it lands.")
            else:
                print("VERDICT: lateral (14) stayed in band while driven (span {} counts).".format(c_span))
                print("         Not reproduced this run; keep the trace on the next app run.")
        if rest:
            p_rest = max(f[5] for f in rest)
            if p_rest > 5:
                print("NOTE: load cell read up to {:.1f} lbs at rest. Either something is".format(p_rest))
                print("      loading the axial pad, or the Mega restarted since the app's")
                print("      last tare (the firmware never tares at boot).")
        print("=" * 64)


def setup_app_gpio():
    """Drive the Pi GPIO lines exactly as the app does at startup, so the probe
    runs under the same electrical conditions. Pins are BCM numbers from
    main/config/constants.py: EMERGENCYSTOP 16 HIGH (= released),
    EXTRAENABLE 17 HIGH (= leg-length driver enabled), EXTRAFORWARD 27 and
    EXTRABACKWARD 22 LOW. Nothing is cleaned up at exit, deliberately: the
    lines stay as the app leaves them."""
    try:
        import RPi.GPIO as GPIO
    except ImportError as exc:
        print("RPi.GPIO not available ({}); --gpio ignored".format(exc))
        return False
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in (16, 17, 22, 27):
        GPIO.setup(pin, GPIO.OUT)
    GPIO.output(16, GPIO.HIGH)
    GPIO.output(17, GPIO.HIGH)
    GPIO.output(27, GPIO.LOW)
    GPIO.output(22, GPIO.LOW)
    print("GPIO set like the app: 16=HIGH (e-stop released), 17=HIGH (leg-length enable), 22/27=LOW")
    return True


def app_is_running():
    try:
        out = subprocess.run(["pgrep", "-f", "kneespa.py"], capture_output=True, text=True)
        return out.returncode == 0 and out.stdout.strip() != ""
    except FileNotFoundError:
        return False


def read_banner(usb_port, seconds=8.0):
    """Reset the Mega through its USB port (DTR pulse) and print what it says
    on boot. The boot banner carries the firmware VERSION. setup() stops all
    motors first, so this is also a safe way to halt a runaway move."""
    print("Opening {} at 9600 and pulsing DTR (this resets the Mega)".format(usb_port))
    try:
        s = serial.Serial(usb_port, 9600, timeout=0.5)
    except Exception as exc:
        print("Could not open {}: {}".format(usb_port, exc))
        return 1
    try:
        s.dtr = False
        time.sleep(0.2)
        s.dtr = True
        end = time.time() + seconds
        while time.time() < end:
            line = s.readline().decode(errors="replace").rstrip()
            if line:
                print("   " + line)
    finally:
        s.close()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default=DEFAULT_PORT)
    ap.add_argument("--target", type=int, default=500, help="axial target in counts for the move test (default 500, ~1 inch out)")
    ap.add_argument("--home", type=int, default=50, help="axial home target in counts (default 50 = the zero mark)")
    ap.add_argument("--rest", type=float, default=5.0, help="seconds of baseline before moving")
    ap.add_argument("--hold", type=float, default=3.0, help="seconds to hold at target before homing")
    ap.add_argument("--pressure", type=float, default=0.0, help="tare, then run a P<lbs> pressure move instead of the position move")
    ap.add_argument("--pressure-seconds", type=float, default=30.0, help="cap on the pressure move before X (default 30)")
    ap.add_argument("--watch", type=float, default=0.0, help="watch only for N seconds; no motion")
    ap.add_argument("--stop", action="store_true", help="send X and exit")
    ap.add_argument("--gpio", action="store_true", help="drive Pi GPIO 16/17 HIGH and 22/27 LOW exactly like the app does, before testing")
    ap.add_argument("--banner", metavar="USB_PORT", help="reset the Mega via its USB port and print the boot banner")
    ap.add_argument("--c-min", type=int, default=LATERAL_BAND[0])
    ap.add_argument("--c-max", type=int, default=LATERAL_BAND[1])
    ap.add_argument("--log", default=os.path.expanduser("~/lateral-probe.log"))
    args = ap.parse_args()

    if args.banner:
        sys.exit(read_banner(args.banner))

    if app_is_running():
        print("The KneeSpa app is running (kneespa.py). Stop it first:  pkill -9 python")
        sys.exit(2)
    if not (100 <= args.target <= 1500):
        print("--target must be between 100 and 1500 counts for this probe.")
        sys.exit(2)
    if args.pressure and not (1 <= args.pressure <= 30):
        print("--pressure must be between 1 and 30 lbs for this probe.")
        sys.exit(2)

    print("port {}  log {}".format(args.port, args.log))
    print("Keep hands clear of the axial actuator. Ctrl+C sends X (stop).")
    if args.gpio:
        setup_app_gpio()
    try:
        probe = Probe(args.port, args.log, (args.c_min, args.c_max))
    except Exception as exc:
        print("Could not open {}: {}".format(args.port, exc))
        sys.exit(1)

    try:
        probe.flush_firmware_buffer()
        probe.command("X", 3.0)  # clear anything a previous session left running
        if args.stop:
            return

        probe.command("HF1", 3.0)  # 1 s status cadence; ack is DONE
        if args.watch > 0:
            probe.set_phase("watch")
            time.sleep(args.watch)
        else:
            probe.set_phase("rest")
            time.sleep(args.rest)

            if args.pressure:
                # Same sequence the app uses: tare (its L0 step tares too),
                # then a pressure move on SMC 12 at PRESSURE_SPEED.
                probe.set_phase("tare")
                probe.command("L1", 8.0)
                time.sleep(1.0)

                probe.set_phase("pressure")
                target = int(args.pressure) if float(args.pressure).is_integer() else args.pressure
                text = probe.command("P{}".format(target), args.pressure_seconds)
                if not text.startswith("DONE"):
                    probe.incomplete.append(("P{}".format(target), text or "no ack within cap"))
                    probe._out("!! pressure move did not complete within {:.0f}s; sending X".format(args.pressure_seconds))
                probe.command("X", 3.0)
                time.sleep(1.0)
            else:
                probe.set_phase("move")
                probe.motion("I12{}".format(args.target), MOVE_TIMEOUT_S)

                probe.set_phase("hold")
                time.sleep(args.hold)

            probe.set_phase("home")
            probe.motion("I12{}".format(args.home), MOVE_TIMEOUT_S)
            time.sleep(2.0)
        probe.command("HF0", 3.0)
    except KeyboardInterrupt:
        print("\nInterrupted: sending X")
        probe.stop()
    except Exception as exc:
        print("\nError: {}: sending X".format(exc))
        probe.stop()
    finally:
        if not args.stop:
            probe.summary()
        probe.close()
        print("raw log: " + args.log)


if __name__ == "__main__":
    main()
