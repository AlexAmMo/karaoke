'use strict';
(() => {
  let popup, nonce, active = false, indicator;
  const securePage = 'https://alexammo.github.io/karaoke/microfono/';
  let stopSignal;
  const text = (tag, value) => {const n = document.createElement(tag); n.textContent=value; return n;};
  function note(message) {if(indicator)indicator.textContent=message;}
  window.closeKaraokeMicrophone = () => {
    KaraokeVoice.stop(); active=false;
    if(popup && !popup.closed)popup.postMessage({kind:'karaoke-room-closed',nonce},new URL(securePage).origin);
    popup = null;
  };
  window.addEventListener('pagehide',window.closeKaraokeMicrophone);
  window.karaokePeople = (content,{api,action,state}) => {
    stopSignal = async () => {active=false;await api('mic-stop',{}).catch(()=>{});note('Micrófono apagado.');};
    const heading=text('h3','Cantantes y entradas');content.append(heading);
    const form=document.createElement('form'); const name=document.createElement('input');name.maxLength=40;name.placeholder='Nombre';name.setAttribute('aria-label','Nuevo cantante');
    const create=text('button','Añadir cantante');form.append(name,create);content.append(form);
    form.onsubmit=e=>{e.preventDefault();if(name.value.trim())action({op:'singer-create',name:name.value.trim()},()=>{name.value='';document.getElementById('settings-button').click();});};
    for(const person of state.singers||[]) {
      const label=text('label',person.name);const select=document.createElement('select');
      select.append(new Option('Entrada automática',''));
      for(const input of state.inputs||[])select.append(new Option(input.label,input.id));
      if(person.preferred && ![...select.options].some(o=>o.value===person.preferred))select.append(new Option('Entrada desconectada',person.preferred));
      select.value=person.preferred||''; label.append(select);content.append(label);
      select.onchange=()=>action({op:'singer-input',id:person.id,input:select.value});
    }
    indicator=text('p','');indicator.setAttribute('role','status');
    const mic=text('button',active?'Desactivar mi micrófono':'Usar este móvil como micrófono');
    content.append(mic,indicator);
    async function assign() {
      for(let i=0;i<12;i++) {
        await new Promise(r=>setTimeout(r,250));
        try {await api('action',{op:'singer-me'});note('Entrada asignada a tu cantante.');return;}catch(e){if(e.status!==409)throw e;}
      }
      throw Error('Aún no se recibe voz. Comprueba el permiso y la conexión.');
    }
    mic.onclick=async()=>{
      try {
        if(active){window.closeKaraokeMicrophone();await stopSignal();mic.textContent='Usar este móvil como micrófono';return;}
        if(window.isSecureContext && navigator.mediaDevices) {
          await KaraokeVoice.start(sdp=>api('mic-offer',{sdp}),stopSignal);active=true;mic.textContent='Desactivar mi micrófono';await assign();
        }else{
          nonce=Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
          popup=window.open(securePage+'#'+new URLSearchParams({host:location.origin,nonce}),'karaoke-microphone');
          if(!popup)throw Error('Permite la ventana del micrófono para continuar.');
          note('Activa el micrófono en la ventana que se ha abierto.');
        }
      }catch(e){note(e.message);}
    };
    window.onKaraokeVoiceMessage=async e=>{
      if(!popup||e.source!==popup||e.origin!==new URL(securePage).origin||e.data?.nonce!==nonce)return;
      if(e.data.kind==='karaoke-mic-stop'){await stopSignal();return;}
      if(e.data.kind!=='karaoke-mic-offer')return;
      try{const answer=await api('mic-offer',{sdp:e.data.sdp});popup.postMessage({kind:'karaoke-mic-answer',nonce,answer},e.origin);active=true;mic.textContent='Desactivar mi micrófono';await assign();}
      catch(err){popup.postMessage({kind:'karaoke-mic-answer',nonce,error:err.message},e.origin);note(err.message);}
    };
  };
  window.addEventListener('message',e=>window.onKaraokeVoiceMessage?.(e));
})();
window.karaokeVoiceEditor = (content,item,state,revision,command) => {
  const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent='Asignar perfiles y micrófonos';details.append(summary);
  const list=document.createElement('div');details.append(list);
  const rows=[];
  function add(voice) {
    if(rows.length>=10)return;
    const row=document.createElement('div');const select=document.createElement('select');select.setAttribute('aria-label','Perfil del cantante');
    if(voice && !voice.singer)select.append(new Option(voice.name,''));
    for(const singer of state.singers)select.append(new Option(singer.name,singer.id));
    if(voice)select.value=voice.singer||'';
    const input=document.createElement('select');input.setAttribute('aria-label','Entrada para este turno');input.append(new Option('Micro preferido',''));
    for(const source of state.inputs)input.append(new Option(source.label,source.id));input.value=voice?.input||'';
    const remove=document.createElement('button');remove.type='button';remove.textContent='Quitar voz';const entry={row,select,input,name:voice?.name};
    remove.onclick=()=>{rows.splice(rows.indexOf(entry),1);row.remove();};row.append(select,input,remove);list.append(row);rows.push(entry);
  }
  (item.voices||[]).forEach(add);
  const append=document.createElement('button');append.textContent='Añadir voz';append.onclick=()=>add(null);
  const save=document.createElement('button');save.textContent='Aplicar asignación';save.onclick=()=>{
    const voices=rows.map(r=>({singer:r.select.value||null,name:r.name,input:r.input.value||null}));
    command('rename',item.id,{voices,revision},'Asignación guardada');
  };
  details.append(append,save);content.append(details);
};
