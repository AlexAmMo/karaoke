"""Capture expected audio formats, size and source identification for this debug build."""
import lldb
t = lldb.debugger.GetSelectedTarget()
p = t.GetProcess()
if p.GetState() in (lldb.eStateStopped, lldb.eStateCrashed):
    def mem(addr,size=8):
        err=lldb.SBError()
        value=p.ReadUnsignedFromMemory(addr,size,err)
        return value if err.Success() else 0
    for thread in p:
        for frame in thread:
            name=frame.GetFunctionName() or ''
            if 'TAUDIOCONVERTER_SWRESAMPLE_$__$$_CONVERT$' in name:
                reg=lambda key:frame.FindRegister(key).GetValueAsUnsigned()
                print('FORMAT COUNTERS', {'input_bytes':mem(reg('x21'),4), 'input_frames':reg('x22'), 'output_capacity_frames':reg('x23')})
                converter=reg('x19')
                for off,label in [(8,'source'),(16,'destination')]:
                    f=mem(converter+off)
                    print('FORMAT OBJECT',label,f,p.ReadMemory(f,24,lldb.SBError()).hex(), 'frame_size',mem(f+20,4))
                thread.SetSelectedFrame(frame.GetFrameID())
                lldb.debugger.HandleCommand('register read x0 x1 x2 x3 x4 x5 x6 x7 x19 x20 x21 x22 x23 x24 x25 x26 x27 x28')
                lldb.debugger.HandleCommand('disassemble --frame')
            if 'TGENERICPLAYBACKSTREAM_$__$$_READDATA' in name:
                stream=mem(frame.GetSP()+16)
                source=mem(stream+32)
                vmt=t.ResolveLoadAddress(mem(source)).GetSymbol().GetName()
                print('STREAM CLASS',vmt,'callback_nbytes',mem(frame.GetSP()+8,4))
                thread.SetSelectedFrame(frame.GetFrameID())
                lldb.debugger.HandleCommand('disassemble --frame')
