/* Audio capture runs only in the secure, visible page which requested permission. */
window.KaraokeVoice = (() => {
  let peer, stream;
  function stop() {
    if (stream) stream.getTracks().forEach(track => track.stop());
    if (peer) peer.close();
    peer = stream = null;
  }
  async function start(signal, ended) {
    stop();
    if (!navigator.mediaDevices?.getUserMedia) throw Error('El micrófono necesita una conexión HTTPS de confianza.');
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount:1,echoCancellation:false,autoGainControl:false,noiseSuppression:false},video:false});
      const connection = new RTCPeerConnection({iceServers:[]});
      peer = connection;
      for (const track of stream.getAudioTracks()) {
        connection.addTrack(track,stream);
        track.addEventListener('ended', () => { if (peer === connection) { stop(); ended?.(); } });
      }
      connection.addEventListener('connectionstatechange',() => {
        if (connection.connectionState === 'failed' && peer === connection) {stop(); ended?.();}
      });
      await connection.setLocalDescription(await connection.createOffer());
      if (connection.iceGatheringState !== 'complete') await new Promise(resolve => {
        const finish = () => {clearTimeout(timer);connection.removeEventListener('icegatheringstatechange',check);resolve();};
        const check = () => {if (connection.iceGatheringState === 'complete') finish();};
        const timer = setTimeout(finish,3000);
        connection.addEventListener('icegatheringstatechange',check);check();
      });
      await connection.setRemoteDescription(await signal(connection.localDescription.sdp));
    } catch (err) { stop(); throw err; }
  }
  window.addEventListener('pagehide',stop);
  return {start,stop};
})();
