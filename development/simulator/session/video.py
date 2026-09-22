"""Locate the optional portable Windows VLC runtime before importing the GUI."""

import os
import sys
from pathlib import Path


def configure_vlc(repo: Path) -> None:
    """Use the workspace copy when present; otherwise use normal VLC discovery.

    Explicit python-vlc environment settings take precedence. Nothing is
    downloaded at launch, and the real player remains optional on other PCs.
    """
    if sys.platform != "win32" or any(
        name in os.environ for name in ("PYTHON_VLC_LIB_PATH", "PYTHON_VLC_MODULE_PATH")
    ):
        return
    runtime = repo / ".cache/vlc/vlc-3.0.23"
    library = runtime / "libvlc.dll"
    plugins = runtime / "plugins"
    if library.is_file() and plugins.is_dir():
        os.environ["PYTHON_VLC_LIB_PATH"] = str(library.resolve())
        os.environ["PYTHON_VLC_MODULE_PATH"] = str(plugins.resolve())
