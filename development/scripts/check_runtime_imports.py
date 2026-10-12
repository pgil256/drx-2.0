#!/usr/bin/env python3
"""Import every module of the Pi application on the running interpreter.

The Raspberry Pi runs Buster's Python 3.7, while the test suite runs on a
current Python. ruff (see ruff.toml) rejects syntax 3.7 cannot parse; this
script goes one step further and executes every module's import-time code,
which also catches names missing from the 3.7 standard library
(``functools.cached_property``, ``typing.Literal``, ...) and annotations that
only evaluate on newer versions.

It cannot see calls made later, such as a keyword argument added in 3.8, so it
complements the tests rather than replacing them. Run it with the interpreter
you want to check:

    python development/scripts/check_runtime_imports.py

Exit code 0 = every module imported, 1 = at least one failed.
"""

import importlib
import os
import sys
import tempfile
import traceback
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN = REPO_ROOT / "runtime" / "raspberry-pi" / "main"

# Hardware and media bindings that exist only on the device (same stand-ins as
# development/tests/conftest.py).
STUBBED = ("RPi", "RPi.GPIO", "PyQt5.QtMultimedia", "PyQt5.QtMultimediaWidgets", "vlc")


def module_names():
    for path in sorted(MAIN.rglob("*.py")):
        parts = path.relative_to(MAIN).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if parts:
            yield ".".join(parts)


def main() -> int:
    for name in STUBBED:
        sys.modules[name] = MagicMock()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(MAIN))

    failures = []
    with tempfile.TemporaryDirectory(prefix="kneespa-import-check-") as device:
        # Keep generated config and logs out of the checkout.
        os.environ["KNEESPA_DEVICE_DIR"] = device
        names = list(module_names())
        for name in names:
            try:
                importlib.import_module(name)
            except Exception:
                failures.append((name, traceback.format_exc()))
        import logging

        logging.shutdown()  # release log files before the directory is removed

    version = ".".join(str(part) for part in sys.version_info[:3])
    for name, detail in failures:
        print("FAILED {}\n{}".format(name, detail))
    print("Python {}: imported {} of {} runtime modules".format(
        version, len(names) - len(failures), len(names)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
