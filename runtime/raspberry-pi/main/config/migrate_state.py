"""Copy legacy device state out of the code tree once, without overwriting it.

This module uses only the standard library and runs before application imports.
It is also usable during the one-time upgrade while the service is stopped.
"""

import argparse
import os
from pathlib import Path
import shutil
from typing import List, Optional


def _copy_missing(source: Path, destination: Path) -> bool:
    """Copy a regular file exclusively and remove incomplete copies on failure."""
    if not source.is_file() or destination.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        target = destination.open("xb")
    except FileExistsError:
        return False
    try:
        with source.open("rb") as stream, target:
            shutil.copyfileobj(stream, target)
            target.flush()
            os.fsync(target.fileno())
        shutil.copystat(source, destination)
    except Exception:
        target.close()
        destination.unlink(missing_ok=True)
        raise
    return True


def migrate_state(project: Path, device: Path) -> List[str]:
    """Preserve legacy calibration, identity, authentication, uploads, and logs.

    Existing destination files win. A completion marker prevents removed state
    (for example revoked users) from being resurrected by a later launch.
    Source files are retained for rollback; no firmware is flashed.
    """
    destination = device / "raspberry-pi"
    marker = destination / ".legacy-migrated"
    if marker.exists():
        return []
    files = [
        ("config/kneespa.cfg", "config/kneespa.cfg"),
        ("main/config/kneespa.cfg", "config/kneespa.cfg"),
        ("main/data/user_pins.csv", "data/user_pins.csv"),
        ("main/data/auth_state.json", "data/auth_state.json"),
        ("main/data/pending_uploads.json", "data/pending_uploads.json"),
        (".env", ".env"),
        ("main/.env", ".env"),
        ("cloud.env", "cloud.env"),
    ]
    for folder in ("logs", "main/logs"):
        source = project / folder
        if source.is_dir():
            files.extend(
                (str(path.relative_to(project)), str(Path("logs") / path.relative_to(source)))
                for path in sorted(source.rglob("*")) if path.is_file()
            )
    copied = []
    for source, relative in files:
        if _copy_missing(project / source, destination / relative):
            copied.append(relative)
    destination.mkdir(parents=True, exist_ok=True)
    marker.touch(exist_ok=True)
    return copied


def migrate_default_state() -> None:
    """Upgrade the local device only; explicitly selected profiles stay isolated."""
    if os.environ.get("KNEESPA_DEVICE_DIR") or os.environ.get("KNEESPA_BASE_DIR"):
        return
    project = Path(__file__).resolve().parents[4]
    migrate_state(project, project / "devices" / "local")


def main(argv: Optional[List[str]] = None) -> int:
    """Run an explicit migration without importing Qt or touching hardware."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--device-dir", type=Path)
    args = parser.parse_args(argv)
    device = args.device_dir or args.project_root / "devices" / "local"
    copied = migrate_state(args.project_root.resolve(), device.resolve())
    print(f"Device state ready at {device.resolve()}: copied {len(copied)} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
