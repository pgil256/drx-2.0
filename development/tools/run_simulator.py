"""Open the real KneeSpa GUI and local 3D hardware simulator together.

Usage: python development/tools/run_simulator.py
Install development/simulator/requirements.txt and build the viewer first.
"""
import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import traceback
import webbrowser
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "development"))


async def supervise(args: argparse.Namespace) -> int:
    """Own backend lifetime and relaunch only the GUI when it requests Restart."""
    from simulator.transport.server import SimulatorServer, VIEWER_DIR
    from simulator.session.processes import SessionProcesses
    from simulator.session.cloud import cloud_environment

    if args.cloud_env:
        credentials = cloud_environment(args.cloud_env)
        print(json.dumps({"cloud_mode": "dashboard",
                          "device_id": credentials["KNEESPA_DEVICE_ID"],
                          "cloud_url": credentials["KNEESPA_CLOUD_URL"]}), flush=True)
    if not args.backend_only and not (VIEWER_DIR / "index.html").is_file():
        raise RuntimeError("Build the viewer first: see development/simulator/README.md")
    directory = ROOT / ".cache/simulator" / (time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}")
    server = SimulatorServer(directory, seed=args.seed)
    child: Optional[subprocess.Popen] = None
    output = None
    processes = None
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    try:
        manifest = await server.start()
        path = directory / "session.json"
        print(json.dumps({"session": str(path), "viewer": manifest["http_url"]}), flush=True)
        viewer_url = manifest["http_url"] + "/#token=" + manifest["token"]
        if not args.no_browser:
            webbrowser.open(viewer_url)
        if args.backend_only:
            if args.duration:
                try:
                    await asyncio.wait_for(stop.wait(), args.duration)
                except asyncio.TimeoutError:
                    pass
            else:
                await stop.wait()
            return 0
        output = (directory / "gui-output.log").open("a", encoding="utf-8")
        while not stop.is_set():
            if processes:
                processes.close()
            # A new GUI generation gets its own job. This also works inside
            # hosts that place each process generation in a different outer job.
            processes = SessionProcesses()
            command = [sys.executable, str(Path(__file__).resolve()), "--gui-session", str(path)]
            if args.capture:
                command += ["--capture", str(args.capture.resolve())]
            if args.duration:
                command += ["--duration", str(args.duration)]
            if args.verify:
                command += ["--verify", args.verify]
            if args.cloud_env:
                command += ["--cloud-env", str(args.cloud_env.resolve())]
            child = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                                     env=processes.environment(),
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            print(json.dumps({"gui_pid": child.pid}), flush=True)
            deadline = time.monotonic() + args.duration + 15 if args.duration else None
            while child.poll() is None and not stop.is_set():
                await asyncio.sleep(0.1)
                if deadline and time.monotonic() > deadline:
                    raise TimeoutError("GUI did not finish its timed verification cleanup")
                if server._ticker.done():
                    server._ticker.result()
            if child.poll() != 75:
                print(json.dumps({"gui_exit_code": child.returncode}), flush=True)
                return child.returncode or 0
    finally:
        # Also owns the actual interpreter behind Windows' venv launcher shim.
        if processes:
            processes.close()
        if child and child.poll() is None:
            child.terminate()
            try:
                await asyncio.wait_for(asyncio.to_thread(child.wait), 5)
            except asyncio.TimeoutError:
                child.kill()
                await asyncio.to_thread(child.wait)
        await server.close()
        if output:
            output.close()
    return 0


def main() -> int:
    from simulator.session.cloud import DEFAULT_CLOUD_ENV

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--duration", type=float, help="Close a verification session after N seconds")
    parser.add_argument("--capture", type=Path, help="Save the actual GUI to a PNG during verification")
    parser.add_argument("--verify", choices=["smoke", "video", "protocols", "faults", "restart", "live",
                                             "ux", "ux-stops", "protocol-1", "protocol-2",
                                             "protocol-3", "protocol-4"],
                        help="Exercise real GUI controls; protocols takes about 22 minutes")
    parser.add_argument("--gui-session", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--cloud", dest="cloud_env", action="store_const",
                        const=DEFAULT_CLOUD_ENV, help="Connect to the saved dashboard profile")
    parser.add_argument("--cloud-env", type=Path,
                        help="Connect to a dashboard using this explicit cloud.env file")
    args = parser.parse_args()
    if args.cloud_env and (args.verify or args.backend_only):
        parser.error("Cloud mode requires the interactive GUI; omit --verify and --backend-only")
    try:
        if args.gui_session:
            from simulator.session.processes import join_session_job
            join_session_job()
            from simulator.session.gui import run_gui
            return run_gui(args.gui_session, args.capture, args.duration,
                           args.verify, args.cloud_env)
        return asyncio.run(supervise(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Simulator failed: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
