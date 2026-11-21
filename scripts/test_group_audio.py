#!/usr/bin/env python3
"""Exercise simultaneous native inputs and the host PCM bridge with a disposable session."""
import argparse
import functools
import math
import os
from pathlib import Path
import secrets
import socket
import struct
import sys
import tempfile
import threading
import time

from test_live_pitch import make_chart
from test_session import Session


@functools.cache
def tone_frames(frequency):
    # Seamless periodic PCM: exact integral cycles over one second, in 20 ms frames.
    samples = [round(8000 * math.sin(2 * math.pi * frequency * n / 48000)) for n in range(48000)]
    return [struct.pack('<960h', *samples[n:n+960]) for n in range(0, 48000, 960)]


def exercise_group(session, chart, count):
    turn = f'group-{count}'
    names = [f'Voz {i + 1}' for i in range(count)]
    secret = secrets.token_hex(16)
    # Alternate independent native inputs and phone-format PCM. One deliberately misses A4.
    routes = [dict(mobile=i % 2 == 0, channel=0, device=i) for i in range(count)]
    session.native('start', token=turn, names=names, chart=str(chart), precision=2,
                   routes=routes, mobile_secret=secret)
    state = session.wait(lambda s: s.get('token') == turn and s['state'] == 'singing')
    assert state['max_singers'] >= count and state['mobile_port'] > 0
    # Send native test tones to the wired slots only. Phone slots must have no synthetic fallback.
    for i in range(1, count, 2):
        session.native('test-tone', player=i, hz=440)
    stop = threading.Event()
    phones = list(range(0, count, 2))
    missed = phones[-1] if count > 2 else -1
    silence = threading.Event()
    endpoint = ('127.0.0.1', state['mobile_port'])
    waveforms = [tone_frames(523 if i == missed else 440) for i in phones]
    def stream():
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            seq = 0
            deadline = time.monotonic()
            while not stop.is_set():
                for i, waveform in zip(phones, waveforms):
                    pcm = waveform[seq % len(waveform)]
                    packet = struct.pack('<32sBI', secret.encode(), i, seq) + pcm
                    if i == 0 and silence.is_set():
                        # Replays and packets from a closed room must not resurrect the note.
                        sock.sendto(struct.pack('<32sBI', b'0'*32, i, seq)+pcm, endpoint)
                        sock.sendto(struct.pack('<32sBI', secret.encode(), i, 0)+pcm, endpoint)
                    else:
                        sock.sendto(packet, endpoint)
                seq += 1
                deadline += 0.02
                stop.wait(max(0, deadline - time.monotonic()))
    worker = threading.Thread(target=stream)
    worker.start()
    try:
        live = session.wait(lambda s: s.get('token') == turn and s['position'] >= 3.0)
        assert len(live['scores']) == count, live['scores']
        assert all(v > 0 for i, v in enumerate(live['scores']) if i != missed), live
        if missed >= 0:
            assert live['scores'][missed] < min(v for i,v in enumerate(live['scores']) if i!=missed), live['scores']
        if count == 10:
            silence.set()
            expired = session.wait(lambda s: s['tones'][0] == -1 and s['position'] >= live['position'] + 0.5)
            paused = session.wait(lambda s: s['position'] >= expired['position'] + 0.5)
            assert paused['scores'][0] == expired['scores'][0], (expired,paused)
            assert paused['scores'][1] > expired['scores'][1]
            assert paused['tones'][0] == -1
            silence.clear()
            resumed = session.wait(lambda s: s['position'] > paused['position'] and s['scores'][0] > paused['scores'][0])
            assert resumed['scores'][0] > paused['scores'][0], (paused, resumed)
    finally:
        stop.set(); worker.join(2)
    session.native('end', token=turn)
    session.wait(lambda s: s.get('token') == turn and s['state']=='idle' and s['mobile_port']==0)
    print('PASS',count,'singers',live['scores'],'audio',state['audio_driver'],state['output_frames'],state['output_hz'],flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',type=Path)
    parser.add_argument('--launcher',type=Path)
    parser.add_argument('--counts',type=int,nargs='+',default=[1,2,3,5,6,10])
    args=parser.parse_args()
    env = dict(os.environ,SDL_AUDIODRIVER='dummy',SDL_AUDIO_DRIVER='dummy')
    if args.engine: env['KARAOKE_ENGINE']=str(args.engine.resolve())
    launcher=[str(args.launcher.resolve())] if args.launcher else [sys.executable,'-m','karaoke.app']
    with tempfile.TemporaryDirectory(prefix='karaoke-group-') as scratch:
        data=Path(scratch)/'data'; data.mkdir()
        chart=make_chart(Path(scratch))
        session=Session(data,launcher,env)
        try:
            session.launch()
            for count in args.counts: exercise_group(session,chart,count)
        except BaseException:
            for file in (data/'engine.log',data/'launcher-1.log'):
                if file.exists(): print(file.name,file.read_text(errors='replace')[-2000:],file=sys.stderr)
            raise
        finally: session.close()

if __name__=='__main__': main()
