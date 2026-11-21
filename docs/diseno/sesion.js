'use strict';
// Datos ilustrativos. La maqueta no abre el micrófono, reproduce medios ni consulta catálogos.
const songs = [
  {title: 'Sigo aquí', artist: 'Álex Ubago', initials: 'ÁU', color: '#355447', state: 'remote'},
  {title: 'Todo un hombre haré de ti', artist: 'Mulán', initials: 'M', color: '#714738', state: 'assisted'},
  {title: 'Lose Yourself', artist: 'Eminem', initials: 'E', color: '#43526a', state: 'remote'},
  {title: 'Por la boca vive el pez', artist: 'Fito & Fitipaldis', initials: 'FF', color: '#644456', state: 'saved'},
  {title: 'On the run', artist: 'Joshua Morin', initials: 'JM', color: '#355447', state: 'remote', cover: 'on-the-run.jpg'},
  {title: 'A contraluz', artist: 'Sesión de prueba', initials: 'SP', color: '#505536', state: 'unavailable'},
];
const statusText = {assisted: 'Requiere al anfitrión', saved: 'Descargada', remote: 'Para descargar', working: 'Preparando…', unavailable: 'Sin edición compatible'};
const queue = [{id: 1, song: songs[3]}];
let lastId = 1;
let section = 'search';
let opened = null;
const byId = id => document.getElementById(id);
const ns = 'http://www.w3.org/2000/svg';
function svgNode(tag, attrs) {
  const node = document.createElementNS(ns, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}
function drawScore() {
  const score = byId('score');
  for (const y of [18, 45, 72, 99, 126]) score.append(svgNode('path', {d: `M0 ${y}H800`, stroke: 'var(--rule)', 'stroke-width': 1}));
  const notes = [[3,104,64], [80,90,88], [184,63,54], [250,76,96], [359,49,80], [450,36,88], [552,50,105], [670,77,61], [743,64,54]];
  for (const [x, y, width] of notes) score.append(svgNode('rect', {x, y, width, height: 9, rx: 4, fill: 'var(--guide)'}));
  score.append(svgNode('path', {d: 'M3 132 Q14 132 22 122 T42 117 T65 113 M80 99 Q90 90 98 95 T116 94 T143 95 L166 94 M184 81 Q196 72 206 68 T234 68 M250 82 Q258 78 271 81 T300 80 L327 80', fill: 'none', stroke: 'var(--accent)', 'stroke-width': 4, 'stroke-linecap':'round'}));
  score.append(svgNode('path', {d: 'M328 3V142', stroke: 'var(--ink)', 'stroke-width': 1.6}));
}
function make(tag, cls, value) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (value) el.textContent = value;
  return el;
}
function normalize(value) {return value.normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase('es')}
function announce(message) {byId('feedback').textContent = message}
function beginDownload(song) {
  if (song.state !== 'remote') return;
  song.state = 'working';
  window.setTimeout(() => {song.state = 'saved'; render(); announce(`${song.title} está lista.`)}, 2600);
}
function add(song) {
  beginDownload(song);
  queue.push({id: ++lastId, song});
  render();
  announce(`${song.title} en el turno ${queue.length}.`);
}
function row(song, turn, position) {
  const li = make('li', 'song');
  const info = make('button', 'song-info');
  const tag = 'song-' + songs.indexOf(song);
  info.dataset.focus = turn ? 'turn-' + turn.id : tag;
  const art = make('span', 'cover', song.initials);
  art.setAttribute('aria-hidden', 'true'); art.style.backgroundColor = song.color;
  if (song.cover) {
    const image = make('img'); image.alt = ''; image.width = 44; image.height = 44;
    image.onload = () => art.replaceChildren(image); image.src = song.cover;
  }
  const text = make('span', 'song-text');
  text.append(make('strong', '', turn ? `${position + 1}. ${song.title}` : song.title), make('small', '', `${song.artist} · ${statusText[song.state]}`));
  info.append(art, text);
  info.onclick = () => openDetail(song, turn);
  li.append(info);
  if (!turn && ['saved','working','remote'].includes(song.state)) {
    const action = make('button', 'action');
    action.dataset.focus = 'add-' + tag;
    action.setAttribute('aria-label', `Añadir ${song.title} a la cola`);
    action.title = 'Añadir a la cola';
    const icon = svgNode('svg', {viewBox: '0 0 24 24', 'aria-hidden': 'true'});
    icon.append(svgNode('path', {d:'M12 4v16M4 12h16', stroke:'currentColor', 'stroke-width':1.8, 'stroke-linecap':'round'}));
    action.append(icon); action.onclick = () => add(song); li.append(action);
  }
  return li;
}
function render() {
  const focused = document.activeElement?.dataset.focus;
  const list = byId('list'); list.replaceChildren();
  byId('count').textContent = queue.length;
  byId('up-next').textContent = queue[0]?.song.title || 'Sin turnos';
  const searching = section === 'search';
  byId('search-view').hidden = !searching;
  byId('list-title').textContent = searching ? 'Canciones' : 'Próximos turnos';
  if (searching) {
    const words = normalize(byId('query').value.trim()).split(/\s+/);
    for (const song of songs) {
      const match = words.every(w => normalize(`${song.title} ${song.artist}`).includes(w));
      if (match && (!byId('saved').checked || song.state === 'saved')) list.append(row(song));
    }
  } else queue.forEach((turn, index) => list.append(row(turn.song, turn, index)));
  byId('empty').hidden = list.children.length > 0;
  byId('empty').textContent = searching ? 'Sin coincidencias. Prueba con una parte del título.' : 'Busca una canción para preparar el primer turno.';
  if (focused) document.querySelector(`[data-focus="${focused}"]`)?.focus({preventScroll:true});
}
function switchSection(next) {
  section = next;
  for (const tab of ['search', 'queue']) {
    const button = byId('show-' + tab);
    if (tab === next) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
  }
  announce(''); render();
}
function openDetail(song, turn) {
  opened = document.activeElement.dataset.focus;
  byId('detail-title').textContent = song.title;
  byId('detail-meta').textContent = `${song.artist} · ${statusText[song.state]}`;
  if (song.cover) byId('detail-meta').textContent += ' · Portada © Joshua Morin (CC BY-SA 2.5)';
  const actions = byId('actions'); actions.replaceChildren();
  function option(label, primary, callback) {
    const btn = make('button', primary ? 'primary' : '', label);
    btn.onclick = () => {byId('detail').close(); callback()}; actions.append(btn);
  }
  if (turn) {
    option('Quitar este turno', false, () => {queue.splice(queue.indexOf(turn), 1); render(); announce('Turno retirado.'); byId('show-queue').focus()});
  } else if (song.state === 'assisted') {
    option('Pedir al anfitrión', true, () => add(song));
  } else if (song.state !== 'unavailable') {
    option('Añadir a la cola', true, () => add(song));
    if (song.state === 'remote') option('Solo descargar', false, () => {beginDownload(song); render(); announce('Descarga de ejemplo iniciada.')});
  }
  byId('detail').showModal();
}
byId('detail').addEventListener('close', () => {
  if (opened && document.activeElement === document.body) document.querySelector(`[data-focus="${opened}"]`)?.focus();
  opened = null;
});
byId('show-search').onclick = () => switchSection('search');
byId('show-queue').onclick = () => switchSection('queue');
byId('query').oninput = render; byId('saved').onchange = render;
function fold(closed) {
  document.querySelector('main').classList.toggle('folded', closed);
  byId('panel').hidden = closed; byId('fold').setAttribute('aria-expanded', String(!closed));
  byId('fold').textContent = closed ? 'Mostrar panel' : 'Ocultar panel';
}
byId('fold').onclick = () => fold(!byId('panel').hidden);
window.matchMedia('(max-width: 740px)').addEventListener('change', ev => {if (ev.matches) fold(false)});
drawScore(); render();
