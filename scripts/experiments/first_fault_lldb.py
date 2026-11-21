"""LLDB Python command for a first-chance exception before Pascal unwinds its frames."""
import lldb


def dump(debugger, command):
    reply = lldb.SBCommandReturnObject()
    debugger.GetCommandInterpreter().HandleCommand(command, reply)
    print(reply.GetOutput() or reply.GetError() or "", flush=True)


def run(debugger):
    target = debugger.GetSelectedTarget()
    loop = target.BreakpointCreateByName("UMAIN_$$_MAINLOOP")
    exception = target.BreakpointCreateByName("fpc_raiseexception")
    if not loop.GetNumLocations() or not exception.GetNumLocations():
        print("FIRSTFAULT diagnostic-error unresolved symbols", loop.GetNumLocations(), exception.GetNumLocations(), flush=True)
        return
    # Set first-chance signal handling before launch so FPC cannot unwind a signal
    # raised while GLEngine is holding a private mutex.
    for sig in ["SIGSEGV", "SIGBUS", "SIGFPE", "SIGILL", "SIGABRT", "SIGTRAP"]:
        dump(debugger, f"process handle -s true -n true -p true {sig}")
    dump(debugger, "run")
    process = target.GetProcess()
    for _ in range(35):
        if process.GetState() not in (lldb.eStateStopped, lldb.eStateCrashed):
            print("FIRSTFAULT diagnostic-error unexpected process state", process.GetState(), flush=True)
            return
        thread = process.GetSelectedThread()
        frames = list(thread.frames)
        names = [(f.GetFunctionName() or "") for f in frames]
        if names and names[0] == "UMAIN_$$_MAINLOOP":
            print("FIRSTFAULT renderer-start-ok", flush=True)
            process.Kill()
            return
        is_raise = names and "raiseexception" in names[0].lower()
        in_render = any("TTEXTURE_OPENGL" in v or "glTex" in v or "glDelete" in v or "ipmap" in v for v in names)
        if not is_raise or in_render:
            print("FIRSTFAULT exception", thread.GetStopDescription(300), names[:25], flush=True)
            dump(debugger, "thread backtrace all -c 30")
            dump(debugger, "register read")
            dump(debugger, "disassemble -p -c 15")
            process.Kill()
            return
        print("FIRSTFAULT ignored Pascal exception", names[:6], flush=True)
        process.Continue()
    print("FIRSTFAULT diagnostic-error exceeded first chance stops", flush=True)
    process.Kill()
