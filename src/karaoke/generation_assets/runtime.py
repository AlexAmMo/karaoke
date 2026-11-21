"""Select a single OpenMP runtime before importing optional native models."""

import os
from pathlib import Path
import platform
import sys
import sysconfig


def configure_intel_openmp():
    if sys.platform != "darwin" or platform.machine() != "x86_64":
        return
    # The pinned Intel PyTorch and CTranslate2 wheels both ship Intel OpenMP
    # with ABI 5.0. Loading both in one process aborts on the first parallel
    # inference. Use CTranslate2's newer ABI-compatible copy for both wheels.
    directory = Path(sysconfig.get_path("platlib")) / "ctranslate2" / ".dylibs"
    if not (directory / "libiomp5.dylib").is_file():
        return
    previous = os.environ.get("DYLD_LIBRARY_PATH", "")
    if previous.split(os.pathsep)[0] == str(directory):
        return
    if os.environ.get("KARAOKE_INTEL_OPENMP") == str(directory):
        raise RuntimeError("El intérprete de generación no admite la configuración de OpenMP en este Mac Intel.")
    env = dict(os.environ, KARAOKE_INTEL_OPENMP=str(directory))
    env["DYLD_LIBRARY_PATH"] = os.pathsep.join(filter(None, (str(directory), previous)))
    # dyld reads search paths at process startup. Keep Python flags and script
    # arguments, including when launched with python -m.
    os.execve(sys.executable, [sys.executable, *sys.orig_argv[1:]], env)
