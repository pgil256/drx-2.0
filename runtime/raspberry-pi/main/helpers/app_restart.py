"""Relaunch the original application mode after its resources have closed."""

import os
import subprocess
import sys
from typing import List, Optional


def restart_app(entry_point: str, arguments: Optional[List[str]] = None) -> None:
    """Retain the interpreter, arguments, environment, cwd and POSIX launcher PID."""
    command = [sys.executable, os.path.abspath(entry_point)]
    command.extend(sys.argv[1:] if arguments is None else arguments)
    if os.name == "posix":
        os.execv(sys.executable, command)
    else:
        subprocess.Popen(command, close_fds=True)
