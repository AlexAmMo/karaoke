"""Exercise QR join, permission, real WebRTC audio, assignment and close from a simulated phone."""
import argparse
import asyncio
from pathlib import Path
import socket
import tempfile
import threading
import time

from playwright.async_api import async_playwright, expect
from karaoke.remote_server import lan_addresses
from karaoke.service import Service

ROOT=Path(__file__).resolve().parents[1]


async def run(host,public):
    with tempfile.TemporaryDirectory(prefix='phone-mic-') as work:
        service=Service(Path(work)); service.remote.start(host);stop=threading.Event()
        def pump():
            while not stop.wait(.02):service.remote.tick()
        thread=threading.Thread(target=pump,daemon=True);thread.start()
        try:
            async with async_playwright() as p:
                browser=await p.chromium.launch(channel='chrome',args=['--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream'])
                context=await browser.new_context(viewport={'width':390,'height':844},permissions=['microphone'])
                if not public:
                    async def asset(route):
                        name=route.request.url.split('/microfono/',1)[1].split('?',1)[0] or 'index.html'
                        file=ROOT/('src/karaoke/remote_web' if name=='voice-capture.js' else 'web-microphone')/name
                        await route.fulfill(path=file)
                    await context.route('https://alexammo.github.io/karaoke/microfono/**',asset)
                page=await context.new_page();await page.goto(service.remote.server.invite_url)
                await page.locator('#name').fill('Luna');await page.locator('#enter').click()
                await page.locator('#settings-button').click();mic=page.get_by_role('button',name='Usar este móvil como micrófono')
                if await page.evaluate('window.isSecureContext'):
                    await mic.click();child=None
                else:
                    async with page.expect_popup() as opened:await mic.click()
                    child=await opened.value;await child.get_by_role('button',name='Activar micrófono').click()
                await expect(page.get_by_text('Entrada asignada a tu cantante.')).to_be_attached(timeout=22000)
                inputs=service.remote.mics.inputs();assert len(inputs)==1,inputs
                assert service.people.list()[0]['preferred'] in inputs
                udp=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);udp.bind(('127.0.0.1',0));udp.setblocking(False)
                try:
                    route=next(iter(inputs));service.remote.mics.route('performance','b'*32,[{'mobile':True,'key':route}]);service.remote.mics.update('performance',dict(token='performance',state='singing',mobile_port=udp.getsockname()[1]))
                    loop=asyncio.get_running_loop();frames=[await asyncio.wait_for(loop.sock_recv(udp,4096),2) for _ in range(3)]
                    assert all(len(f)==1957 and f.startswith(b'b'*32) for f in frames)
                finally:udp.close()
                if child:
                    await child.get_by_role('button',name='Desactivar micrófono').click()
                else:
                    await page.get_by_role('button',name='Desactivar mi micrófono').click()
                end=time.monotonic()+5
                while service.remote.mics.inputs() and time.monotonic()<end:await asyncio.sleep(.06)
                assert not service.remote.mics.inputs()
                await browser.close()
                print('PASS mobile QR, permission, WebRTC, assigned input, three PCM frames and stop ('+('HTTPS helper' if child else 'secure localhost')+')',flush=True)
        finally:
            stop.set();thread.join();service.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--lan',action='store_true');parser.add_argument('--public',action='store_true');args=parser.parse_args()
    asyncio.run(run(lan_addresses()[0] if args.lan else '127.0.0.1',args.public))
