"""Launch the compiled renderer under LLDB until the first native fault."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

output = Path("build/first-fault").resolve()
engine = Path(sys.argv[1]).resolve()
driver = Path(__file__).with_name("first_fault_lldb.py").resolve()
assert os.environ["SDL_AUDIODRIVER"] == "dummy" and os.environ["SDL_AUDIO_DRIVER"] == "dummy"
for attempt in range(1, int(sys.argv[2]) + 1):
    with tempfile.TemporaryDirectory(prefix="karaoke-firstfault-") as scratch:
        scratch = Path(scratch)
        ipc = scratch / "ipc"
        ipc.mkdir()
        songs = scratch / "empty"
        songs.mkdir()
        config = scratch / "engine.ini"
        config.write_text("[Game]\nPlayers=1\nDifficulty=Medium\nMicDelay=0\n[Graphics]\nFullScreen=Off\nResolution=1280x800\nScreens=1\n[Advanced]\nScreenFade=Off\n[Sound]\nBackgroundMusic=Off\nAudioVolume=65\nPreviewVolume=0\nVoicePassthrough=On\n")
        logfile = output / f"attempt-{attempt:02d}.log"
        args = ["lldb", "-b", "-o", "settings set target.disable-aslr false",
                "-o", f"command script import {driver}", "-o", "script first_fault_lldb.run(lldb.debugger)",
                "--", str(engine), "-window", "-resolution", "1280x800", "-configfile",
                str(config), "-scorefile", str(scratch / "scores.sqlite3"), "-songpath", str(songs)]
        env = dict(os.environ, KARAOKE_IPC=str(ipc), KARAOKE_TEST_INPUT="1")
        with logfile.open("w") as report:
            try:
                result = subprocess.run(args, cwd=engine.parent, env=env, timeout=55,
                                        stdout=report, stderr=subprocess.STDOUT)
                print(f"{attempt} lldb={result.returncode}", flush=True)
            except subprocess.TimeoutExpired:
                print(f"{attempt} timeout", flush=True)
        transcript = logfile.read_text()
        print("\n".join(l for l in transcript.splitlines() if "FIRSTFAULT" in l), flush=True)
        if "FIRSTFAULT exception" in transcript or "FIRSTFAULT diagnostic-error" in transcript:
            break
