"""Read the libsndfile PEAK bookkeeping timestamp separately from all PCM data."""
import struct
from pathlib import Path

def peak_time(stream):
    if stream.read(4)!=b"RIFF":
        raise ValueError("Expected held RIFF FLOAT stem")
    stream.seek(8)
    if stream.read(4)!=b"WAVE":
        raise ValueError("Expected WAVE")
    while len(header:=stream.read(8))==8:
        name,length=struct.unpack("<4sI",header)
        if name==b"PEAK" and length==24:
            if stream.read(4)!=b"\x01\x00\x00\x00": raise ValueError("Unexpected PEAK chunk")
            at=stream.tell()
            return at,struct.unpack("<I",stream.read(4))[0]
        stream.seek(length+(length&1),1)
    raise ValueError("Missing timestamp chunk")

def set_peak_time(path,expected):
    with Path(path).open("r+b") as stream:
        at,_=peak_time(stream)
        stream.seek(at);stream.write(struct.pack("<I",expected))
