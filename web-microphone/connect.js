'use strict';
// No account, media, URL of the song, or join secret reaches this static origin.
const params = new URLSearchParams(location.hash.slice(1));
const origin = params.get('host');
const nonce = params.get('nonce');
const statusLine = document.getElementById('status');
const enable = document.getElementById('enable');
const stopButton = document.getElementById('stop');
const parentWindow = window.opener;
history.replaceState(null, '', location.pathname);
function hostAllowed(value) {
  try {
    const u = new URL(value);
    return (
      u.origin === value &&
      ['http:', 'https:'].includes(u.protocol) &&
      (/^(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|169\.254\.\d+\.\d+|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+)$/.test(
        u.hostname,
      ) ||
        u.hostname.endsWith('.local'))
    );
  } catch {
    return false;
  }
}
function tell(kind, data = {}) {
  parentWindow.postMessage({ kind, nonce, ...data }, origin);
}
function stop() {
  KaraokeVoice.stop();
  tell('karaoke-mic-stop');
  stopButton.hidden = true;
  enable.hidden = false;
  statusLine.textContent = 'Micrófono apagado. Puedes seguir usando el mando.';
}
if (parentWindow && hostAllowed(origin) && /^[a-f0-9]{32}$/.test(nonce || '')) {
  enable.hidden = false;
  statusLine.textContent =
    'La voz se envía al ordenador de la sala a través de la red local.';
  enable.onclick = async () => {
    enable.disabled = true;
    try {
      await KaraokeVoice.start(
        (sdp) =>
          new Promise((resolve, reject) => {
            const timer = setTimeout(() => {
              window.removeEventListener('message', receive);
              reject(Error('El mando no respondió. Vuelve a abrirlo.'));
            }, 13000);
            function receive(e) {
              if (
                e.origin !== origin ||
                e.source !== parentWindow ||
                e.data?.nonce !== nonce ||
                e.data?.kind !== 'karaoke-mic-answer'
              )
                return;
              clearTimeout(timer);
              window.removeEventListener('message', receive);
              if (e.data.error) reject(Error(e.data.error));
              else resolve(e.data.answer);
            }
            window.addEventListener('message', receive);
            tell('karaoke-mic-offer', { sdp });
          }),
        stop,
      );
      enable.hidden = true;
      stopButton.hidden = false;
      statusLine.textContent =
        'El micrófono está activo. Mantén esta página abierta mientras cantas.';
    } catch (err) {
      statusLine.textContent = err.message;
    } finally {
      enable.disabled = false;
    }
  };
  stopButton.onclick = stop;
  window.addEventListener('message', (ev) => {
    if (
      ev.source === parentWindow &&
      ev.origin === origin &&
      ev.data?.nonce === nonce &&
      ev.data?.kind === 'karaoke-room-closed'
    )
      stop();
  });
  window.addEventListener('pagehide', () => tell('karaoke-mic-stop'));
}
