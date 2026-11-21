import asyncio
import socket
import struct
from fractions import Fraction

import numpy as np
from aiortc import AudioStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from av import AudioFrame

from karaoke.mobile_voice import MobileVoices


class TestTone(AudioStreamTrack):
    __test__ = False

    def __init__(self):
        super().__init__(); self.samples = 0

    async def recv(self):
        await asyncio.sleep(.02)
        samples=np.arange(960)+self.samples
        sound=(np.sin(samples*(2*np.pi*440/48000))*8000).astype('int16')[None,:]
        f=AudioFrame.from_ndarray(sound,format='s16',layout='mono');f.pts=self.samples
        f.sample_rate=48000;f.time_base=Fraction(1,48000);self.samples+=960
        return f


def test_webrtc_received_only_for_current_performer_and_room():
    async def run():
        receiver=MobileVoices();pc=RTCPeerConnection(RTCConfiguration(iceServers=[]))
        sender=TestTone();pc.addTrack(sender)
        udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.bind(('127.0.0.1',0));udp.setblocking(False)
        try:
            await pc.setLocalDescription(await pc.createOffer())
            answer=await asyncio.to_thread(receiver.submit,'guest','Ana','mic-offer',{'sdp':pc.localDescription.sdp})
            await pc.setRemoteDescription(RTCSessionDescription(**answer))
            for _ in range(100):
                if receiver.inputs():break
                await asyncio.sleep(.035)
            assert receiver.inputs()['mobile:guest']['label']=='Móvil de Ana'
            receiver.route('turn','a'*32,[{'mobile':True,'key':'mobile:guest'}]);receiver.update('turn',{'token':'turn','state':'singing','mobile_port':udp.getsockname()[1]})
            pkt=await asyncio.wait_for(asyncio.get_running_loop().sock_recv(udp,4096),2)
            key,slot,seq=struct.unpack('<32sBI',pkt[:37]);assert (key,slot,seq)==(b'a'*32,0,0)
            assert len(pkt)==1957 and np.max(np.abs(np.frombuffer(pkt[37:],dtype='<i2')))>100
            receiver.update('other',{'token':'turn','state':'singing','mobile_port':udp.getsockname()[1]})
            await asyncio.sleep(.1)
            try: late=udp.recv(4096)
            except BlockingIOError: late=b''
            assert not late
        finally:
            sender.stop();await pc.close();await asyncio.to_thread(receiver.stop);udp.close()
        assert not receiver.inputs()
    asyncio.run(run())
