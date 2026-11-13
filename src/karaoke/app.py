"""Desktop launcher and local service lifecycle."""

from __future__ import annotations
import argparse
import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from .service import Service


def data_directory():
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Karaoke"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Karaoke"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "karaoke"


def resources():
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return exe.parent.parent / "Resources" if sys.platform == "darwin" else exe.parent
    return Path(__file__).resolve().parents[2]


def engine_path():
    if os.environ.get("KARAOKE_ENGINE"):
        return Path(os.environ["KARAOKE_ENGINE"]).resolve()
    base = resources()
    if sys.platform == "darwin":
        folder = (
            base / "Engine.app"
            if getattr(sys, "frozen", False)
            else base / "build/engine/UltraStar Deluxe.app"
        )
        return folder / "Contents/MacOS/ultrastardx"
    return base / (
        "engine/ultrastardx.exe"
        if getattr(sys, "frozen", False)
        else "build/engine/game/ultrastardx.exe"
    )


@contextlib.contextmanager
def instance_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    file = path.open("a+b")
    try:
        if sys.platform == "win32":
            import msvcrt

            if path.stat().st_size == 0:
                file.write(b"0")
                file.flush()
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        file.close()


def run(root, demo=False, window_size="1280x800"):
    root.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        root.chmod(0o700)
    engine = engine_path()
    if not engine.is_file():
        raise RuntimeError(
            "No se encuentra el motor. Construye la app con scripts/build_macos.sh o instala el paquete completo."
        )
    service = Service(root)
    if demo:
        fixture_root = resources() / "technical-spike/fixtures"
        charts = [fixture_root / "initial/A/song.txt", fixture_root / "staging/B/song.txt"]
        for chart in charts:
            if chart.is_file():
                service.add_import(str(chart))
        service.fields["player1"] = "Prueba A4"
        service.fields["player2"] = "Prueba B4"
        os.environ["KARAOKE_TEST_INPUT"] = "1"
    config = root / "engine.ini"
    if not config.exists():
        config.write_text(
            "[Game]\nPlayers=1\nDifficulty=Medium\nMicDelay=0\n[Graphics]\nFullScreen=Off\nResolution=1280x800\nScreens=1\n[Advanced]\nScreenFade=Off\n[Sound]\nBackgroundMusic=Off\nAudioVolume=65\nPreviewVolume=0\nVoicePassthrough=On\n",
            encoding="utf-8",
        )
    empty = root / "engine-empty"
    empty.mkdir(exist_ok=True)
    service.tick()
    env = dict(os.environ, KARAOKE_IPC=str(service.ipc))
    if not demo:
        env.pop("KARAOKE_TEST_INPUT", None)
    log = (root / "engine.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            str(engine),
            "-window",
            "-resolution",
            window_size,
            "-configfile",
            str(config),
            "-scorefile",
            str(root / "scores.sqlite3"),
            "-songpath",
            str(empty),
        ],
        cwd=engine.parent,
        env=env,
        stdout=log,
        stderr=log,
    )
    stop = False

    def signal_handler(*_):
        nonlocal stop
        stop = True

    previous = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, signal_handler)
    try:
        while process.poll() is None and not stop:
            service.tick()
            time.sleep(0.08)
        if process.returncode not in (None, 0):
            raise RuntimeError(
                f"El motor se ha cerrado con código {process.returncode}. Consulta {root / 'engine.log'}."
            )
    finally:
        if process.poll() is None:
            service.command("quit")
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
        service.close()
        log.close()
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def main():
    bin_path = resources() / "bin"
    if bin_path.exists():
        os.environ["PATH"] = str(bin_path) + os.pathsep + os.environ.get("PATH", "")
        os.environ["KARAOKE_FFMPEG_DIR"] = str(bin_path)
    if len(sys.argv) >= 3 and sys.argv[1] == "--worker":
        if sys.argv[2] == "karaoke.provider":
            from .provider import main as worker_main
        elif sys.argv[2] == "karaoke.picker":
            from .picker import main as worker_main
        else:
            raise SystemExit("Unknown worker")
        worker_main()
        return
    parser = argparse.ArgumentParser(description="Karaoke local con biblioteca y cola")
    parser.add_argument("--data-dir", type=Path, default=data_directory())
    parser.add_argument(
        "--demo", action="store_true", help="Prueba sintética de desarrollo; no valida micrófonos"
    )
    parser.add_argument(
        "--window-size",
        choices=["1000x640", "1280x800", "1600x900", "1920x1080"],
        default="1280x800",
        help="Tamaño lógico de la ventana; mantiene el escalado Retina del monitor.",
    )
    parser.add_argument("--version", action="version", version="Karaoke 0.1.0")
    args = parser.parse_args()
    try:
        with instance_lock(args.data_dir / "app.lock"):
            run(args.data_dir.resolve(), args.demo, args.window_size)
    except (BlockingIOError, PermissionError):
        print(
            "Karaoke ya está abierto o no se puede acceder a su carpeta de datos.", file=sys.stderr
        )
        raise SystemExit(1)
    except Exception as exc:
        args.data_dir.mkdir(parents=True, exist_ok=True)
        (args.data_dir / "last-error.txt").write_text(str(exc), encoding="utf-8")
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
