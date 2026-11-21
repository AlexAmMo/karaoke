"""Keep the launcher out of GuardMalloc, then save real first-chance backtraces for its child."""
from pathlib import Path
import os
import subprocess
import sys

engine=Path(os.environ["KARAOKE_PROBE_ENGINE"])
launcher=next(p for p in engine.parents if p.suffix==".app" and p.name=="Karaoke.app")/"Contents/MacOS/karaoke"
out=Path("build/guard").resolve()
wrapper=out/"probe-engine"
wrapper.write_text("""#!/bin/bash
set -u
cd "$(dirname "$KARAOKE_PROBE_ENGINE")"
export SDL_AUDIO_DRIVER=dummy SDL_AUDIODRIVER=dummy
log="$GUARD_DATA/lldb-$(date +%s)-$$.log"
universal="-o"
cmd=(lldb --batch -o 'settings set target.disable-aslr false')
cmd+=(-o "settings set target.env-vars DYLD_INSERT_LIBRARIES=/usr/lib/libgmalloc.dylib MALLOC_PROTECT_BEFORE=$GUARD_BEFORE MALLOC_STRICT_SIZE=1")
cmd+=(-o 'process handle -s true -n true -p true SIGSEGV SIGBUS SIGFPE SIGABRT')
cmd+=(-o run -k 'thread backtrace all' -k 'register read' -k 'disassemble -p -c 16')
cmd+=(-o 'thread backtrace all' -o 'register read' -- "$KARAOKE_PROBE_ENGINE" "$@")
exec "${cmd[@]}" > "$log" 2>&1
""")
# GuardMalloc uses the presence of MALLOC_PROTECT_BEFORE, even when its contents would be 0.
if os.environ["SIDE"]=="after":
    wrapper.write_text(wrapper.read_text().replace(" MALLOC_PROTECT_BEFORE=$GUARD_BEFORE",""))
wrapper.chmod(0o755)
env=dict(os.environ,KARAOKE_ENGINE=str(wrapper),GUARD_BEFORE="1",GUARD_DATA=str(out))
for i in range(1,5):
    print("guarded session",i,flush=True)
    try:
        s=subprocess.run([sys.executable,"scripts/test_session.py","--launcher",str(launcher),"--check-panel",
                        "--output",str(out/f"summary-{i}.json"),"--failure-logs",str(out/f"logs-{i}")],env=env,
                        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=150,text=True)
        (out/f"session-{i}.log").write_text(s.stdout)
    except subprocess.TimeoutExpired:
        print("Session timed out",flush=True)
        break
    if s.returncode:
        break
