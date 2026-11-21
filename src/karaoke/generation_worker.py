"""Optional local singing chart worker. Run with the separate charting Python environment."""

from __future__ import annotations

import argparse
from fractions import Fraction
from collections import Counter
import contextlib
import gc
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import zipfile

CREATOR_REV = '39d3eb5f9fb1e24220c4ca58888af8a88e11a38a'
CREATOR_SHA = 'd6ba3f9fc96a2db719f4ac3cb90ea642724381a8c552730c35d7baff0f534750'
ASR_REPO = 'mobiuslabsgmbh/faster-whisper-large-v3-turbo'
ASR_REV = '0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf'
SEPARATOR_REV = 'cbc8a9b1a87023b7fd74e7b3412e6321c0eab003'
SEPARATOR_SHA = 'd9fa14133cfcc034a6758923bb3a8ca9f8dfd0b582134643bbf83f72c17576dd'
MODELS_REV = '75854108a364f01f8ee0a3df0db9ce8eb902beca'
TOKEN = re.compile(r'[^\W_]+', re.UNICODE)
APP_AGENT = 'Karaoke/0.2 (https://github.com/AlexAmMo/karaoke)'
# Exact, unmodified source from the pinned GPLv3 program. No user-controlled file names.
ENGINE_FILES = ('utils/__init__.py', 'utils/logger.py', 'services/__init__.py', *(
    f'services/{module}.py' for module in ('alignment_whisper', 'consonant_trim', 'forced_alignment',
    'game_notes', 'hyphenation', 'melisma', 'model_mirror', 'note_holds', 'note_pipeline',
    'pitch_detection', 'ultrastar')))


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def notify(stage):
    print(json.dumps({'stage': stage}, ensure_ascii=False), file=sys.stderr, flush=True)


def default_cache():
    if os.getenv('KARAOKE_GENERATION_CACHE'):
        return Path(os.environ['KARAOKE_GENERATION_CACHE'])
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Caches/Karaoke/charting'
    return Path(os.getenv('LOCALAPPDATA', Path.home() / '.cache')) / 'Karaoke/charting'


def load_engine(cache):
    backend = cache / f'creator-{CREATOR_REV}'
    if not (backend / 'LICENSE').is_file():
        cache.mkdir(parents=True, exist_ok=True)
        url = f'https://codeload.github.com/retotito/UltrastarCreatorTool/zip/{CREATOR_REV}'
        with tempfile.TemporaryDirectory(dir=cache) as tmp:
            stage = Path(tmp) / 'source'
            stage.mkdir()
            archive = Path(tmp) / 'source.zip'
            with urlopen(Request(url, headers={'User-Agent': APP_AGENT}), timeout=60) as response:
                contents = response.read(16_000_001)
            if len(contents) > 16_000_000 or hashlib.sha256(contents).hexdigest() != CREATOR_SHA:
                raise ValueError('La verificación del motor de generación ha fallado.')
            archive.write_bytes(contents)
            prefix = f'UltrastarCreatorTool-{CREATOR_REV}/'
            with zipfile.ZipFile(archive) as zipped:
                for name in ENGINE_FILES:
                    target = stage / name
                    target.parent.mkdir(exist_ok=True, parents=True)
                    target.write_bytes(zipped.read(prefix + 'backend/' + name))
                (stage / 'LICENSE').write_bytes(zipped.read(prefix + 'LICENSE'))
            try:
                stage.rename(backend)
            except OSError:
                if not (backend / 'LICENSE').is_file():
                    raise
    sys.path.insert(0, str(backend))


def prepare(cache, profile, model_dir=None):
    from huggingface_hub import hf_hub_download, snapshot_download
    notify('Preparando modelos locales')
    pins = {'asr': str(model_dir) if model_dir else ASR_REPO + '@' + ASR_REV,
            'separator': 'adefossez/HTDemucs@' + SEPARATOR_REV}
    def cached(download, *args, **kwargs):
        try:
            return download(*args, local_files_only=True, **kwargs)
        except FileNotFoundError:
            return download(*args, **kwargs)
        except Exception as exc:
            from huggingface_hub.errors import LocalEntryNotFoundError
            if not isinstance(exc, LocalEntryNotFoundError):
                raise
            return download(*args, **kwargs)

    whisper = model_dir or cached(snapshot_download, ASR_REPO, revision=ASR_REV,
                                 allow_patterns=['model.bin', '*.json', '*.txt'])
    separator = cached(hf_hub_download, 'adefossez/HTDemucs', '955717e8.safetensors', revision=SEPARATOR_REV)
    if digest(separator) != SEPARATOR_SHA:
        raise ValueError('La firma de la separación vocal no coincide.')
    if profile == 'quality':
        load_engine(cache)
        from services import forced_alignment, game_notes, model_mirror, pitch_detection
        for model in (forced_alignment.SUNG_MODEL, pitch_detection.FCPE_MODEL):
            if digest(model_mirror.fetch(model)) != model['sha256']:
                raise ValueError('La firma de un modelo vocal no coincide.')
        game_notes.download(str(cache))
        pins.update(alignment='Retotito/ultrastar-models@' + MODELS_REV,
                    pitch='FCPE@' + MODELS_REV, notes='openvpi/GAME@' + game_notes.MODEL_VERSION,
                    code='retotito/UltrastarCreatorTool@' + CREATOR_REV)
    return whisper, separator, pins


def normalize(text):
    plain = ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))
    return ' '.join(TOKEN.findall(plain))


def choose_candidate(candidates, transcript, artist, title, duration):
    """A near-exact artist and work, duration, and ordered acoustic transcription all corroborate text."""
    from rapidfuzz.fuzz import ratio
    recognized = normalize(transcript)
    if len(recognized.split()) < 12:
        return None
    titles, artists = normalize(title), normalize(artist)
    matches = []
    for row in candidates:
        if not isinstance(row, dict) or row.get('instrumental'):
            continue
        text = row.get('plainLyrics')
        if not isinstance(text, str) or not (0 < len(text) <= 60_000):
            continue
        try:
            delta = abs(float(row['duration']) - duration)
            source_id = int(row['id'])
        except (TypeError, ValueError, KeyError):
            continue
        if not math.isfinite(delta) or delta > min(12, max(6, .04 * duration)):
            continue
        if normalize(str(row.get('trackName') or '')) != titles:
            continue
        author = normalize(str(row.get('artistName') or ''))
        if not author or not (author == artists or ratio(author, artists) >= 90):
            continue
        candidate = normalize(text)
        similarity = ratio(recognized, candidate) / 100
        length = len(candidate.split()) / len(recognized.split())
        if similarity >= .79 and .78 <= length <= 1.25:
            matches.append((similarity, -delta, source_id, text))
    if not matches:
        return None
    score, _, source_id, lyrics = max(matches)
    return lyrics, {'kind': 'lrclib', 'id': source_id, 'agreement': round(score, 3)}


def lookup(transcript, artist, title, duration):
    query = urlencode({'artist_name': artist, 'track_name': title})
    try:
        request = Request('https://lrclib.net/api/search?' + query, headers={'User-Agent': APP_AGENT})
        with urlopen(request, timeout=8) as response:
            raw = response.read(2_000_001)
        if len(raw) <= 2_000_000:
            rows = json.loads(raw)
            if isinstance(rows, list):
                return choose_candidate(rows, transcript, artist, title, duration)
    except (OSError, ValueError):
        pass  # The transcription is available even when the optional external lyrics source is down.
    return None


def split_vocals(audio, directory, separator):
    import soundfile as sf
    import torch
    from demucs.apply import apply_model
    decoded = directory / 'mix.wav'
    subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-i', str(audio), '-map', '0:a:0',
                    '-vn', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_f32le', str(decoded)], check=True)
    samples, rate = sf.read(decoded, dtype='float32', always_2d=True)
    wave = torch.from_numpy(samples.T.copy())
    del samples
    mono = wave.mean(0)
    mean, std = mono.mean(), mono.std()
    if std < 1e-7:
        raise ValueError('No se ha encontrado señal en la grabación.')
    # The pinned safetensors has one HTDemucs and no executable checkpoint state.
    # Direct initialization also supports the last PyTorch build for Intel macOS.
    from demucs.htdemucs import HTDemucs
    from safetensors import safe_open
    with safe_open(separator, framework='pt') as weights:
        meta = weights.metadata()
        kwargs = json.loads(meta['kwargs'])
        segment = kwargs['segment']
        kwargs['segment'] = Fraction(segment['numerator'], segment['denominator'])
        model = HTDemucs(**kwargs)
        model.load_state_dict({k: weights.get_tensor(k) for k in weights.keys()})
    model.eval()
    with torch.inference_mode():
        stems = apply_model(model, ((wave - mean) / std)[None], device='cpu', shifts=0,
                            overlap=.25, split=True, progress=False, num_workers=0)
    vocals = stems[0, model.sources.index('vocals')] * std + mean
    voice = directory / 'vocals.wav'
    sf.write(voice, vocals.T.numpy(), rate, subtype='FLOAT')
    decoded.unlink()
    return voice, len(mono) / rate


def transcribe(voice, whisper, language):
    from faster_whisper import WhisperModel
    model = WhisperModel(str(whisper), device='cpu', compute_type='int8', cpu_threads=3)
    segments, detail = model.transcribe(str(voice), language=None if language == 'auto' else language,
                                        beam_size=5, word_timestamps=True, vad_filter=False,
                                        condition_on_previous_text=False)
    words = [[{'word': w.word.strip(), 'start': float(w.start), 'end': float(w.end)}
              for w in (segment.words or []) if w.end > w.start and TOKEN.search(w.word)] for segment in segments]
    return [line for line in words if line], detail.language


def safe_text(value, maximum=180):
    return ' '.join(''.join(c if c.isprintable() else ' ' for c in value).split())[:maximum]


def chart_text(notes, title, artist, language, duration):
    """Write relative UltraStar pitch with a 16.67 ms grid and preserve end-of-word spaces."""
    rows = [f'#TITLE:{safe_text(title)}', f'#ARTIST:{safe_text(artist)}', '#MP3:audio.mp3',
            f'#LANGUAGE:{safe_text(language)}', '#BPM:900', '#GAP:0', '#EDITION:Borrador local']
    previous_line, last_end, count = None, 0, 0
    for note in notes:
        text = note['syllable']
        clean = ''.join(c for c in text if c.isprintable()).replace('\u00a0', ' ')
        # Upstream uses an inserted '-' at an internal syllable boundary.
        if clean.endswith('-'):
            clean = clean[:-1]
        if not clean.strip():
            continue
        line = note['line_index']
        start = max(last_end, round(note['start'] * 60))
        stop = min(math.floor(duration * 60), max(start + 1, round(note['end'] * 60)))
        if stop <= start:
            continue
        if previous_line is not None and line != previous_line:
            rows.append(f'- {last_end}')
        pitch = note.get('pitch')
        kind = 'F' if note.get('is_rap') or pitch is None else ':'
        rows.append(f'{kind} {start} {stop-start} {0 if pitch is None else int(pitch)-60} {clean}')
        previous_line, last_end, count = line, stop, count + 1
    if not count:
        raise ValueError('La grabación no produjo notas vocales utilizables.')
    return '\n'.join([*rows, 'E', ''])


def standard_notes(voice, words):
    import librosa
    import numpy as np
    signal, sr = librosa.load(voice, sr=16000)
    # Independent permissive-weight mode. Unvoiced words are never given guessed note targets.
    f0, voiced, _ = librosa.pyin(signal, fmin=65, fmax=950, sr=sr, frame_length=1024, hop_length=160)
    notes = []
    for line, spans in enumerate(words):
        for word in spans:
            start, end = word['start'], word['end']
            a, b = round(start * 100), max(round(start * 100) + 1, round(end * 100))
            frequencies = f0[a:b][voiced[a:b]]
            pitch = round(69 + 12 * math.log2(float(np.median(frequencies)) / 440)) if len(frequencies) >= 3 else None
            notes.append({'syllable': word['word'] + ' ', 'start': start, 'end': end, 'line_index': line, 'pitch': pitch})
    return notes


def musical_events(voice, timing, cache, language):
    import soundfile as sf
    from services import game_notes
    chunks = []
    # Overlapping local contexts keep memory independent of song length. Only the middle
    # of each window owns its events, so the network can see notes on both sides of a seam.
    with sf.SoundFile(voice) as stream:
        sr = stream.samplerate
        duration = len(stream) / sr
        for window in range(0, math.ceil(duration), 12):
            start, stop = max(0, window - 1.5), min(duration, window + 13.5)
            if not any(t['start'] < stop and t['end'] > start for t in timing):
                continue
            stream.seek(round(start * sr))
            signal = stream.read(round((stop-start) * sr), dtype='float32', always_2d=True).mean(axis=1)
            for a, b, voiced, midi in game_notes.extract(game_notes.model_folder(str(cache)), signal, [], language):
                middle = start + (a+b) / 2
                if voiced and window <= middle < window+12 and b > a:
                    chunks.append((max(0, start+a), min(duration, start+b), round(midi)))
    # Adjacent windows can describe overlapping pieces of the same note.
    events = []
    for a, b, midi in sorted(chunks):
        if events and a < events[-1][1]:
            prev_a, prev_b, prev_pitch = events[-1]
            if prev_pitch == midi:
                events[-1] = (prev_a, max(b, prev_b), midi)
                continue
            seam = (a + prev_b) / 2
            events[-1] = (prev_a, seam, prev_pitch)
            a = seam
        if b > a:
            events.append((a, b, midi))
    return events


def join_syllables_and_notes(syllables, events, pitch, duration):
    """Use two independent observations: consonant/word anchors from CTC and note events from GAME."""
    import numpy as np
    from bisect import bisect_left, bisect_right
    starts = [event[0] for event in events]
    ends = [event[1] for event in events]
    anchors = []
    for i, syllable in enumerate(syllables):
        anchor = syllable['start']
        next_start = syllables[i+1]['start'] if i+1 < len(syllables) else duration
        previous = anchors[-1] if anchors else 0
        candidates = starts[bisect_left(starts, max(previous+.045, anchor-.08)):
                            bisect_right(starts, min(next_start-.045, anchor+.10))]
        if candidates:
            anchor = min(candidates, key=lambda t: abs(t - anchor))
        anchors.append(max(previous, anchor))
    frames, f0 = np.asarray(pitch['times']), np.asarray(pitch['frequencies'])
    result = []
    for i, syllable in enumerate(syllables):
        a = anchors[i]
        next_a = anchors[i+1] if i+1 < len(anchors) else duration
        # A musical hold often outlasts the last consonant. Preserve the acoustic
        # note events up to the next syllable, stopping in an actual interlude.
        b = min(next_a, max(a + .045, syllable['end']) + 10.0)
        available = events[bisect_right(ends, a):bisect_left(starts, b)]
        relevant = []
        release = max(a, syllable['end'])
        for event in available:
            if event[0] > release + .25:
                break
            relevant.append(event)
            release = max(release, event[1])
        rendered = []
        for left, right, midi in relevant:
            left, right = max(a, left), min(b, right)
            if right-left < .035:
                continue
            if rendered and rendered[-1]['pitch'] == midi and left-rendered[-1]['end'] < .045:
                rendered[-1]['end'] = right
            else:
                rendered.append(dict(syllable, start=left, end=right, pitch=int(midi), musical_support=1.0))
        if not rendered:
            right = min(next_a, max(a + .02, syllable['end']))
            first, last = np.searchsorted(frames, (a, right))
            voiced = f0[first:last]; voiced = voiced[voiced > 0]
            midi = None
            if len(voiced) >= 3:
                contour = np.rint(69 + 12 * np.log2(voiced/440)).astype(int)
                midi = int(Counter(contour).most_common(1)[0][0])
            rendered.append(dict(syllable, start=a, end=right, pitch=midi, musical_support=0.0))
        text = syllable['syllable']
        for part, note in enumerate(rendered):
            if len(rendered) > 1:
                note['syllable'] = text.rstrip() if part == 0 else '~'
                if part == len(rendered)-1 and text.endswith(' '):
                    note['syllable'] += ' '
            result.append(note)
    return result


def chart_quality(voice, lyrics, language, cache):
    from services import forced_alignment, hyphenation, pitch_detection
    syllables = hyphenation.hyphenate_lyrics(lyrics, language)['hyphenated']
    notify('Alineando sílabas y voz')
    pitch = pitch_detection.detect_pitches_fcpe(str(voice))
    timing = forced_alignment.align_lyrics(str(voice), syllables, pitch_data=pitch, language=language)
    if not timing:
        raise ValueError('No se pudo alinear la letra con la voz.')
    notify('Calculando notas y prolongaciones')
    events = musical_events(voice, timing, cache, language)
    if not events:
        raise ValueError('No se detectó una melodía vocal que pueda convertirse en notas.')
    import soundfile as sf
    notes = join_syllables_and_notes(timing, events, pitch, sf.info(voice).duration)
    uncertain = [{'start': round(t['start'], 3), 'end': round(t['end'], 3)} for t in notes
                 if t.get('low_confidence') or t['pitch'] is None or t['musical_support'] < .25]
    stats = {'syllables': len(timing), 'musical_events': len(events), 'uncertain_notes': len(uncertain),
             'review_regions': uncertain[:120]}
    return notes, stats


def generate(args):
    import torch
    torch.set_num_threads(3)
    audio, output, cache = args.audio.resolve(), args.output.resolve(), args.cache.resolve()
    if not audio.is_file() or output.exists():
        raise ValueError('Se necesita un archivo de audio y una carpeta de salida nueva.')
    if args.lyrics and args.profile == 'standard':
        raise ValueError('La alineación de una letra aportada requiere el perfil de alta calidad.')
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which('ffmpeg') is None:
        raise ValueError('FFmpeg no está disponible en el entorno de Karaoke.')
    whisper, separator, pins = prepare(cache, args.profile, args.model_dir)
    with tempfile.TemporaryDirectory(prefix='.karaoke-chart-', dir=output.parent) as work:
        work = Path(work)
        payload = work / 'package'
        payload.mkdir()
        notify('Separando la voz de la mezcla original')
        voice, duration = split_vocals(audio, work, separator)
        gc.collect()
        notify('Transcribiendo la letra')
        words, language = transcribe(voice, whisper, args.language)
        transcript = '\n'.join(' '.join(w['word'] for w in spans) for spans in words)
        if not words:
            raise ValueError('No se reconoció una voz con letra suficiente para generar el mapa.')
        lyrics, source = transcript, {'kind': 'asr'}
        if args.lyrics:
            if args.lyrics.stat().st_size > 160_000:
                raise ValueError('El texto de la letra excede el tamaño que admite el alineador.')
            lyrics, source = args.lyrics.read_text(encoding='utf-8-sig'), {'kind': 'user'}
        elif args.lookup_lyrics and args.profile == 'quality':
            selected = lookup(transcript, args.artist, args.title, duration)
            if selected:
                lyrics, source = selected
        if args.profile == 'quality':
            notes, stats = chart_quality(voice, lyrics, language, cache)
        else:
            notify('Calculando la melodía vocal')
            notes, stats = standard_notes(voice, words), {}
        chart = payload / 'song.txt'
        chart.write_text(chart_text(notes, args.title, args.artist, language, duration), encoding='utf-8')
        # Keep the artist's original vocal mix. Decode only when the source is not an MP3 stream.
        preserved = audio.suffix.lower() == '.mp3'
        if preserved:
            shutil.copyfile(audio, payload / 'audio.mp3')
        else:
            subprocess.run(['ffmpeg', '-nostdin', '-loglevel', 'error', '-i', str(audio), '-map', '0:a:0',
                            '-vn', '-c:a', 'libmp3lame', '-q:a', '2', str(payload / 'audio.mp3')], check=True)
        report = {'schema': 1, 'state': 'draft', 'automatically_verified': False, 'profile': args.profile,
                  'method': 'sung-ctc+free-game+fcpe' if args.profile == 'quality' else 'whisper-pyin',
                  'language': language, 'duration': duration, 'lyrics': source, 'models': pins,
                  'input_sha256': digest(audio), 'audio_sha256': digest(payload / 'audio.mp3'),
                  'chart_sha256': digest(chart), 'chart': 'song.txt', 'audio': 'audio.mp3', 'notes': len(notes),
                  'diagnostics': stats}
        (payload / 'generation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        payload.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--profile', choices=('quality', 'standard'), default='quality')
    parser.add_argument('--cache', type=Path, default=default_cache())
    parser.add_argument('--model-dir', type=Path)
    parser.add_argument('--audio', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--title')
    parser.add_argument('--artist')
    parser.add_argument('--language', choices=('auto', 'es', 'en'), default='auto')
    parser.add_argument('--lyrics', type=Path)
    parser.add_argument('--lookup-lyrics', action='store_true')
    args = parser.parse_args()
    if not args.prepare and not all((args.audio, args.output, args.title, args.artist)):
        parser.error('Se necesitan --audio, --output, --title y --artist.')
    try:
        # Libraries may write logs to stdout. The caller receives exactly one JSON result there.
        with contextlib.redirect_stdout(sys.stderr):
            if args.prepare:
                _, _, pins = prepare(args.cache.resolve(), args.profile, args.model_dir)
                result = {'schema': 1, 'profile': args.profile, 'state': 'installed', 'models': pins}
            else:
                result = generate(args)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    except (ValueError, OSError, RuntimeError, ImportError, subprocess.SubprocessError) as exc:
        print(safe_text(str(exc), 500), file=sys.stderr, flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
