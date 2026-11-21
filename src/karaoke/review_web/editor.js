'use strict';
const get=id=>document.getElementById(id);let data,lines,rows=[],beat,gap,highlight,dirty=false;
async function request(options){const r=await fetch('chart',options);const d=await r.json();if(!r.ok)throw Error(d.error||'No se pudo guardar el mapa.');return d;}
function draw(){
  get('title').textContent=data.title;get('artist').textContent=data.artist;beat=15/Number(String(data.bpm).replace(',','.'));gap=Number(String(data.gap).replace(',','.'))/1000;
  lines=data.body.split('\n');get('raw').value=data.body;const body=get('notes');body.replaceChildren();rows=[];highlight=null;
  lines.forEach((line,index)=>{
    const m=/^([:*FRG])\s+(-?\d+)\s+(\d+)\s+(-?\d+) (.*)$/.exec(line);if(!m)return;
    const tr=document.createElement('tr');const cell=el=>{const td=document.createElement('td');td.append(el);tr.append(td);return el;};
    const jump=cell(document.createElement('button'));jump.textContent='Escuchar';
    function input(label,val,numeric){const el=cell(document.createElement('input'));el.type=numeric?'number':'text';if(numeric)el.step='any';el.setAttribute('aria-label',label);el.value=val;return el;}
    const lyric=input('Sílaba',m[5],false),start=input('Inicio',(+m[2]*beat+gap).toFixed(3),true),dur=input('Duración',(+m[3]*beat).toFixed(3),true),pitch=input('Altura UltraStar',m[4],true);
    const type=cell(document.createElement('select'));type.setAttribute('aria-label','Tipo de nota');for(const [k,l] of [[':','Normal'],['*','Dorada'],['F','Libre'],['R','Rap'],['G','Rap dorado']])type.append(new Option(l,k));type.value=m[1];
    jump.onclick=()=>{get('audio').currentTime=Math.max(0,+start.value-.15);get('audio').play().catch(err=>get('status').textContent=err.message);};
    tr.oninput=()=>{dirty=true;lines[index]=`${type.value} ${Math.round((+start.value-gap)/beat)} ${Math.max(1,Math.round(+dur.value/beat))} ${Math.round(+pitch.value)} ${lyric.value}`;get('raw').value=lines.join('\n');};
    body.append(tr);rows.push({tr,start,dur,pitch,type});
  });
  const locked=data.state==='approved';for(const id of ['save','approve','apply','raw'])get(id).disabled=locked;
  body.querySelectorAll('input, select').forEach(el=>el.disabled=locked);
}
get('raw').oninput=()=>dirty=true;
get('apply').onclick=()=>{data.body=get('raw').value;draw();dirty=true;};
get('audio').ontimeupdate=()=>{const t=get('audio').currentTime;const row=rows.find(r=> +r.start.value<=t && t< +r.start.value + +r.dur.value);if(row!==highlight){highlight?.tr.classList.remove('current');row?.tr.classList.add('current');highlight=row;}};
async function save(approve){try{data=await request({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({body:get('raw').value,revision:data.revision,approve})});dirty=false;draw();get('status').textContent=approve?'Guardada en Buscar como edición revisada. Puedes cerrar esta ventana.':'Borrador guardado.';}catch(e){get('status').textContent=e.message;}}
get('save').onclick=()=>save(false);get('approve').onclick=()=>save(true);
window.onbeforeunload=e=>{if(dirty){e.preventDefault();e.returnValue='';}};
request().then(value=>{data=value;draw();}).catch(e=>get('status').textContent=e.message);
const guide=get('guide');let context,oscillator,volume,animation;
function silence(){if(volume&&context)volume.gain.setTargetAtTime(0,context.currentTime,.012);}
function listenToGuide(){
  cancelAnimationFrame(animation);
  if(!guide.checked||get('audio').paused||!context){silence();return;}
  const t=get('audio').currentTime;
  const match=rows.find(r=>+r.start.value<=t && t<+r.start.value+ +r.dur.value);
  if(match && !['F','R','G'].includes(match.type.value)){
    oscillator.frequency.setTargetAtTime(261.625565*Math.pow(2,+match.pitch.value/12),context.currentTime,.008);
    volume.gain.setTargetAtTime(.09,context.currentTime,.012);
  }else silence();
  animation=requestAnimationFrame(listenToGuide);
}
guide.onchange=async()=>{
  if(guide.checked&&!context){context=new AudioContext();oscillator=context.createOscillator();volume=context.createGain();volume.gain.value=0;oscillator.type='sine';oscillator.connect(volume).connect(context.destination);oscillator.start();}
  if(context?.state==='suspended')await context.resume();listenToGuide();
};
get('audio').addEventListener('play',listenToGuide);get('audio').addEventListener('pause',silence);window.addEventListener('pagehide',()=>{silence();context?.close();});
