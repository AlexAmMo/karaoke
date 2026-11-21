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

CREATOR_REV = "39d3eb5f9fb1e24220c4ca58888af8a88e11a38a"
CREATOR_SHA = "d6ba3f9fc96a2db719f4ac3cb90ea642724381a8c552730c35d7baff0f534750"
ASR_REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
ASR_REV = "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
SEPARATOR_REV = "cbc8a9b1a87023b7fd74e7b3412e6321c0eab003"
SEPARATOR_SHA = "d9fa14133cfcc034a6758923bb3a8ca9f8dfd0b582134643bbf83f72c17576dd"
MODELS_REV = "75854108a364f01f8ee0a3df0db9ce8eb902beca"
REFINER_REPO = "tuneperfect/tunestudio-note-refiners"
REFINER_REV = "a770e8194a70c5b5f7dce8ab3b44fbe77db1a5a0"
REFINER_SHA = "87c66621cdf07fa7d1fe481638c23d2ec868367a0908be75c83974d74cea52f7"
NOTE_SEED = 113
TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
APP_AGENT = "Karaoke/0.2 (https://github.com/AlexAmMo/karaoke)"
# Exact, unmodified source from the pinned GPLv3 program. No user-controlled file names.
ENGINE_FILES = (
    "utils/__init__.py",
    "utils/logger.py",
    "services/__init__.py",
    *(
        f"services/{module}.py"
        for module in (
            "alignment_whisper",
            "forced_alignment",
            "game_notes",
            "hyphenation",
            "model_mirror",
            "pitch_detection",
        )
    ),
)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def notify(stage):
    print(json.dumps({"stage": stage}, ensure_ascii=False), file=sys.stderr, flush=True)


def default_cache():
    if os.getenv("KARAOKE_GENERATION_CACHE"):
        return Path(os.environ["KARAOKE_GENERATION_CACHE"])
    if sys.platform == "darwin":
        return Path.home() / "Library/Caches/Karaoke/charting"
    return Path(os.getenv("LOCALAPPDATA", Path.home() / ".cache")) / "Karaoke/charting"


def load_engine(cache):
    backend = cache / f"creator-{CREATOR_REV}"
    if not (backend / "LICENSE").is_file():
        cache.mkdir(parents=True, exist_ok=True)
        url = f"https://codeload.github.com/retotito/UltrastarCreatorTool/zip/{CREATOR_REV}"
        with tempfile.TemporaryDirectory(dir=cache) as tmp:
            stage = Path(tmp) / "source"
            stage.mkdir()
            archive = Path(tmp) / "source.zip"
            with urlopen(Request(url, headers={"User-Agent": APP_AGENT}), timeout=60) as response:
                contents = response.read(16_000_001)
            if len(contents) > 16_000_000 or hashlib.sha256(contents).hexdigest() != CREATOR_SHA:
                raise ValueError("La verificación del motor de generación ha fallado.")
            archive.write_bytes(contents)
            prefix = f"UltrastarCreatorTool-{CREATOR_REV}/"
            with zipfile.ZipFile(archive) as zipped:
                for name in ENGINE_FILES:
                    target = stage / name
                    target.parent.mkdir(exist_ok=True, parents=True)
                    target.write_bytes(zipped.read(prefix + "backend/" + name))
                (stage / "LICENSE").write_bytes(zipped.read(prefix + "LICENSE"))
            try:
                stage.rename(backend)
            except OSError:
                if not (backend / "LICENSE").is_file():
                    raise
    sys.path.insert(0, str(backend))


def prepare(cache, profile, model_dir=None):
    from huggingface_hub import hf_hub_download, snapshot_download

    notify("Preparando modelos locales")
    pins = {
        "asr": str(model_dir) if model_dir else ASR_REPO + "@" + ASR_REV,
        "separator": "adefossez/HTDemucs@" + SEPARATOR_REV,
    }

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

    whisper = model_dir or cached(
        snapshot_download,
        ASR_REPO,
        revision=ASR_REV,
        allow_patterns=["model.bin", "*.json", "*.txt"],
    )
    separator = cached(
        hf_hub_download, "adefossez/HTDemucs", "955717e8.safetensors", revision=SEPARATOR_REV
    )
    if digest(separator) != SEPARATOR_SHA:
        raise ValueError("La firma de la separación vocal no coincide.")
    if profile == "quality":
        load_engine(cache)
        from services import forced_alignment, game_notes, model_mirror, pitch_detection

        for model in (forced_alignment.SUNG_MODEL, pitch_detection.FCPE_MODEL):
            if digest(model_mirror.fetch(model)) != model["sha256"]:
                raise ValueError("La firma de un modelo vocal no coincide.")
        game_notes.download(str(cache))
        refiner = cached(hf_hub_download, REFINER_REPO, "notefix.onnx", revision=REFINER_REV)
        if digest(refiner) != REFINER_SHA:
            raise ValueError("La firma del corrector de tono no coincide.")
        pins.update(
            alignment="Retotito/ultrastar-models@" + MODELS_REV,
            pitch="FCPE@" + MODELS_REV,
            notes="openvpi/GAME@" + game_notes.MODEL_VERSION,
            notes_seed=NOTE_SEED,
            refiner=REFINER_REPO + "@" + REFINER_REV,
            code="retotito/UltrastarCreatorTool@" + CREATOR_REV,
        )
    return whisper, separator, pins


def normalize(text):
    plain = "".join(
        c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c)
    )
    return " ".join(TOKEN.findall(plain))


def text_agreement(first, second):
    """Order-sensitive token overlap, also works in the lightweight host test suite."""
    from difflib import SequenceMatcher

    return SequenceMatcher(
        None, normalize(first).split(), normalize(second).split(), autojunk=False
    ).ratio()


def artist_names(artist):
    # A soundtrack may credit the film first and put its performer in parentheses.
    # Do not break a duet into independent solo artists or erase edition qualifiers.
    return {normalize(artist), *(normalize(s) for s in re.findall(r"\(([^()]+)\)", artist))} - {""}


def candidate_editions(candidates, artist, title, duration):
    titles, artists = normalize(title), artist_names(artist)
    for row in candidates:
        if not isinstance(row, dict) or row.get("instrumental"):
            continue
        text = row.get("plainLyrics")
        if not isinstance(text, str) or not (0 < len(text) <= 60_000):
            continue
        try:
            delta = abs(float(row["duration"]) - duration)
            source_id = int(row["id"])
        except (TypeError, ValueError, KeyError):
            continue
        if not math.isfinite(delta) or delta > min(12, max(6, 0.04 * duration)):
            continue
        if normalize(str(row.get("trackName") or "")) != titles:
            continue
        if artist_names(str(row.get("artistName") or "")).intersection(artists):
            yield delta, source_id, text


def ordered_word_agreement(heard, lyrics):
    """Exact longest common subsequence, with one bit per lyric token and linear memory."""
    columns = {}
    for i, token in enumerate(lyrics):
        columns[token] = columns.get(token, 0) | (1 << i)
    # A set bit marks a column where the prefix LCS increases by one.
    row = 0
    for token in heard:
        matches = columns.get(token, 0) | row
        row = matches & ~(matches - ((row << 1) | 1))
    return 2 * row.bit_count() / max(1, len(heard) + len(lyrics))


def repeated_lyric_agreement(heard, lyrics, seconds_apart):
    """Repeated refrains can attract a greedy match to the wrong occurrence."""
    if len(heard) < 96 or not 0.94 <= len(lyrics) / len(heard) <= 1.06 or seconds_apart > 4:
        return None
    agreement = ordered_word_agreement(heard, lyrics)
    if agreement < 0.90:
        return None
    thirds = [
        ordered_word_agreement(
            heard[len(heard) * i // 3 : len(heard) * (i + 1) // 3],
            lyrics[len(lyrics) * i // 3 : len(lyrics) * (i + 1) // 3],
        )
        for i in range(3)
    ]
    return (agreement, min(thirds)) if min(thirds) >= 0.84 else None


def choose_candidate(candidates, transcript, artist, title, duration, *, rescue=None):
    """Corroborate the work, edition, duration and sung text before accepting words."""
    from difflib import SequenceMatcher

    recognized = normalize(transcript).split()
    if len(recognized) < 12:
        return None
    matches, partial, repeated = [], [], []
    for delta, source_id, text in candidate_editions(candidates, artist, title, duration):
        tokens = normalize(text).split()
        length = len(tokens) / len(recognized)
        if not 0.78 <= length <= (2.6 if rescue else 1.25):
            continue
        matcher = SequenceMatcher(None, recognized, tokens, autojunk=False)
        similarity = matcher.ratio()
        if length <= 1.25 and similarity >= 0.78:
            matches.append((similarity, -delta, source_id, text))
        elif length > 1.25 and rescue:
            # A missing verse can leave a very accurate but incomplete first pass.
            # Only pay for another inference when the words already heard support this edition.
            covered = sum(block.size for block in matcher.get_matching_blocks()) / len(recognized)
            if covered >= 0.85:
                partial.append((source_id, text, covered, delta))
        else:
            evidence = repeated_lyric_agreement(recognized, tokens, delta)
            if evidence:
                agreement, weakest = evidence
                repeated.append((agreement, weakest, -delta, source_id, text))
    if matches:
        score, _, source_id, lyrics = max(matches)
        return lyrics, {"kind": "lrclib", "id": source_id, "agreement": round(score, 3)}
    if repeated:
        agreement, weakest, _, source_id, lyrics = max(repeated)
        return lyrics, {
            "kind": "lrclib",
            "id": source_id,
            "agreement": round(agreement, 3),
            "agreement_method": "ordered_repetitions",
            "weakest_third": round(weakest, 3),
        }
    if not partial:
        return None
    alternate = normalize(rescue()).split()
    if len(alternate) < 1.20 * len(recognized):
        return None
    corrected = []
    for source_id, text, covered, delta in partial:
        tokens = normalize(text).split()
        if not 0.88 <= len(tokens) / len(alternate) <= 1.13:
            continue
        score = SequenceMatcher(None, alternate, tokens, autojunk=False).ratio()
        if score >= 0.85:
            corrected.append((score, covered, -delta, source_id, text))
    if not corrected:
        return None
    score, covered, _, source_id, lyrics = max(corrected)
    return lyrics, {
        "kind": "lrclib",
        "id": source_id,
        "agreement": round(score, 3),
        "recovered_with_windows": True,
        "first_pass_word_coverage": round(covered, 3),
    }


def lookup(transcript, artist, title, duration, *, rescue=None):
    candidates = []
    for name in [artist, *sorted(artist_names(artist) - {normalize(artist)})]:
        try:
            query = urlencode({"artist_name": name, "track_name": title})
            request = Request(
                "https://lrclib.net/api/search?" + query, headers={"User-Agent": APP_AGENT}
            )
            with urlopen(request, timeout=8) as response:
                raw = response.read(2_000_001)
            if len(raw) <= 2_000_000:
                rows = json.loads(raw)
                if isinstance(rows, list):
                    candidates.extend(rows)
        except (OSError, ValueError):
            continue  # ASR remains available when the optional external source is down.
    return choose_candidate(candidates, transcript, artist, title, duration, rescue=rescue)


def split_vocals(audio, directory, separator):
    import soundfile as sf
    import torch
    from demucs.apply import apply_model

    decoded = directory / "mix.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            str(audio),
            "-map",
            "0:a:0",
            "-vn",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "pcm_f32le",
            str(decoded),
        ],
        check=True,
    )
    signal = sf.info(decoded)
    if not 0.5 < signal.duration <= 1200:
        raise ValueError("Se necesita una grabación de entre medio segundo y veinte minutos.")
    samples, rate = sf.read(decoded, dtype="float32", always_2d=True)
    wave = torch.from_numpy(samples.T.copy())
    del samples
    mono = wave.mean(0)
    mean, std = mono.mean(), mono.std()
    if std < 1e-7:
        raise ValueError("No se ha encontrado señal en la grabación.")
    # The pinned safetensors has one HTDemucs and no executable checkpoint state.
    # Direct initialization also supports the last PyTorch build for Intel macOS.
    from demucs.htdemucs import HTDemucs
    from safetensors import safe_open

    with safe_open(separator, framework="pt") as weights:
        meta = weights.metadata()
        kwargs = json.loads(meta["kwargs"])
        segment = kwargs["segment"]
        kwargs["segment"] = Fraction(segment["numerator"], segment["denominator"])
        model = HTDemucs(**kwargs)
        model.load_state_dict({k: weights.get_tensor(k) for k in weights.keys()})

    class VocalsOnly(torch.nn.Module):
        # Demucs normally accumulates all four full-length stems. Its public segment
        # loop can accumulate just the selected channel with identical overlap weights.
        sources = ("vocals",)

        def __init__(self, separator):
            super().__init__()
            self.separator = separator
            self.segment = separator.segment
            self.samplerate = separator.samplerate
            self.vocal_index = separator.sources.index("vocals")

        def valid_length(self, length):
            return self.separator.valid_length(length)

        def forward(self, samples):
            sources = self.separator(samples)
            return sources[:, self.vocal_index : self.vocal_index + 1].contiguous()

    frame_count = len(mono)
    del mono
    wave.sub_(mean).div_(std)
    with torch.inference_mode():
        stems = apply_model(
            VocalsOnly(model).eval(),
            wave[None],
            device="cpu",
            shifts=0,
            overlap=0.25,
            split=True,
            progress=False,
            num_workers=0,
        )
        vocals = stems[0, 0].mul_(std).add_(mean)
    voice = directory / "vocals.wav"
    sf.write(voice, vocals.T.numpy(), rate, subtype="FLOAT")
    decoded.unlink()
    return voice, frame_count / rate


def transcribe(voice, whisper, language, model=None, *, windowed=False):
    import soundfile as sf
    from scipy.signal import resample_poly

    samples, rate = sf.read(voice, dtype="float32", always_2d=True)
    if not len(samples):
        return [], language
    factor = math.gcd(16000, rate)
    waveform = resample_poly(samples.mean(axis=1), 16000 // factor, rate // factor)
    del samples
    # Test exact digital silence, without treating a quiet singer as absent.
    if not waveform.any():
        return [], language
    if model is None:
        from faster_whisper import WhisperModel

        model = WhisperModel(str(whisper), device="cpu", compute_type="int8", cpu_threads=3)
    duration = len(waveform) / 16000
    chunk_size = 24 if windowed else max(1, math.ceil(duration))
    words = []
    detected = language
    for offset in range(0, math.ceil(duration), chunk_size):
        left = max(0, offset - 3) if windowed else 0
        right = min(duration, offset + chunk_size + 3)
        chunk = waveform[round(left * 16000) : round(right * 16000)]
        if not chunk.any():
            continue
        segments, detail = model.transcribe(
            chunk,
            language=None if detected == "auto" else detected,
            beam_size=5,
            word_timestamps=True,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        detected = detail.language
        for segment in segments:
            line = []
            for w in segment.words or []:
                middle = left + (w.start + w.end) / 2
                if w.end <= w.start or not TOKEN.search(w.word):
                    continue
                if windowed and not offset <= middle < offset + chunk_size:
                    continue
                line.append(
                    {
                        "word": w.word.strip(),
                        "start": float(left + w.start),
                        "end": float(left + w.end),
                    }
                )
            if line:
                words.append(line)
    return words, detected


def recover_transcript(voice, whisper, language):
    notify("Comprobando un tramo que falta en la transcripción")
    lines, _ = transcribe(voice, whisper, language, windowed=True)
    return " ".join(w["word"] for line in lines for w in line)


def safe_text(value, maximum=180):
    return " ".join("".join(c if c.isprintable() else " " for c in value).split())[:maximum]


def chart_text(notes, title, artist, language, duration):
    """Write relative UltraStar pitch with a 16.67 ms grid and preserve end-of-word spaces."""
    rows = [
        f"#TITLE:{safe_text(title)}",
        f"#ARTIST:{safe_text(artist)}",
        "#MP3:audio.mp3",
        f"#LANGUAGE:{safe_text(language)}",
        "#BPM:900",
        "#GAP:0",
        "#EDITION:Generada localmente",
    ]
    previous_line, last_end, count = None, 0, 0
    phrase_chars, phrase_words, phrase_start, word_finished = 0, 0, 0, False
    for note in notes:
        text = note["syllable"]
        clean = "".join(c for c in text if c.isprintable()).replace("\u00a0", " ")
        # Upstream uses an inserted '-' at an internal syllable boundary.
        if clean.endswith("-"):
            clean = clean[:-1]
        if not clean.strip():
            continue
        line = note["line_index"]
        start = max(last_end, round(note["start"] * 60))
        stop = min(math.floor(duration * 60), max(start + 1, round(note["end"] * 60)))
        if stop <= start:
            continue
        wrap = word_finished and (
            phrase_chars >= 44
            or phrase_words >= 8
            or start - phrase_start >= 480
            or start - last_end >= 84
        )
        if previous_line is None or line != previous_line or wrap:
            if previous_line is not None:
                rows.append(f"- {last_end}")
            phrase_chars, phrase_words, phrase_start = 0, 0, start
        word_finished = clean.endswith(" ")
        phrase_chars += len(clean.replace("~", ""))
        phrase_words += int(word_finished)
        pitch = note.get("pitch")
        kind = "F" if note.get("is_rap") or pitch is None else ":"
        rows.append(
            f"{kind} {start} {stop - start} {0 if pitch is None else int(pitch) - 60} {clean}"
        )
        previous_line, last_end, count = line, stop, count + 1
    if not count:
        raise ValueError("La grabación no produjo notas vocales utilizables.")
    return "\n".join([*rows, "E", ""])


def standard_notes(voice, words):
    import librosa
    import numpy as np

    signal, sr = librosa.load(voice, sr=16000)
    # Independent permissive-weight mode. Unvoiced words are never given guessed note targets.
    f0, voiced, _ = librosa.pyin(
        signal, fmin=65, fmax=950, sr=sr, frame_length=1024, hop_length=160
    )
    notes = []
    for line, spans in enumerate(words):
        for word in spans:
            start, end = word["start"], word["end"]
            a, b = round(start * 100), max(round(start * 100) + 1, round(end * 100))
            frequencies = f0[a:b][voiced[a:b]]
            pitch = (
                round(69 + 12 * math.log2(float(np.median(frequencies)) / 440))
                if len(frequencies) >= 3
                else None
            )
            notes.append(
                {
                    "syllable": word["word"] + " ",
                    "start": start,
                    "end": end,
                    "line_index": line,
                    "pitch": pitch,
                }
            )
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
            if not any(t["start"] < stop and t["end"] > start for t in timing):
                continue
            stream.seek(round(start * sr))
            signal = stream.read(round((stop - start) * sr), dtype="float32", always_2d=True).mean(
                axis=1
            )
            for a, b, voiced, midi in game_notes.extract(
                game_notes.model_folder(str(cache)), signal, [], language
            ):
                middle = start + (a + b) / 2
                if voiced and window <= middle < window + 12 and b > a:
                    chunks.append((max(0, start + a), min(duration, start + b), round(midi)))
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
        anchor = syllable["start"]
        next_start = syllables[i + 1]["start"] if i + 1 < len(syllables) else duration
        previous = anchors[-1] if anchors else 0
        candidates = starts[
            bisect_left(starts, max(previous + 0.045, anchor - 0.08)) : bisect_right(
                starts, min(next_start - 0.045, anchor + 0.10)
            )
        ]
        if candidates:
            anchor = min(candidates, key=lambda t: abs(t - anchor))
        anchors.append(max(previous, anchor))
    frames, f0 = np.asarray(pitch["times"]), np.asarray(pitch["frequencies"])
    result = []
    for i, syllable in enumerate(syllables):
        a = anchors[i]
        next_a = anchors[i + 1] if i + 1 < len(anchors) else duration
        # A musical hold often outlasts the last consonant. Preserve the acoustic
        # note events up to the next syllable, stopping in an actual interlude.
        b = min(next_a, max(a + 0.045, syllable["end"]) + 10.0)
        available = events[bisect_right(ends, a) : bisect_left(starts, b)]
        relevant = []
        release = max(a, syllable["end"])
        for event in available:
            if event[0] > release + 0.25:
                break
            relevant.append(event)
            release = max(release, event[1])
        rendered = []
        for left, right, midi in relevant:
            left, right = max(a, left), min(b, right)
            if right - left < 0.035:
                continue
            if rendered and rendered[-1]["pitch"] == midi and left - rendered[-1]["end"] < 0.045:
                rendered[-1]["end"] = right
            else:
                rendered.append(
                    dict(syllable, start=left, end=right, pitch=int(midi), musical_support=1.0)
                )
        if not rendered:
            right = min(next_a, max(a + 0.02, syllable["end"]))
            first, last = np.searchsorted(frames, (a, right))
            voiced = f0[first:last]
            voiced = voiced[voiced > 0]
            midi = None
            if len(voiced) >= 3:
                contour = np.rint(69 + 12 * np.log2(voiced / 440)).astype(int)
                midi = int(Counter(contour).most_common(1)[0][0])
            rendered.append(dict(syllable, start=a, end=right, pitch=midi, musical_support=0.0))
        text = syllable["syllable"]
        for part, note in enumerate(rendered):
            if len(rendered) > 1:
                note["syllable"] = text.rstrip() if part == 0 else "~"
                if part == len(rendered) - 1 and text.endswith(" "):
                    note["syllable"] += " "
            result.append(note)
    return result


def configure_inference(cache):
    """Bound the seven CPU thread pools in the pinned ONNX backend on shared party computers."""
    import onnxruntime as ort
    from services import forced_alignment, game_notes, model_mirror, pitch_detection

    options = ort.SessionOptions()
    options.intra_op_num_threads = min(3, os.cpu_count() or 1)
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")

    def session(path):
        return ort.InferenceSession(
            str(path), sess_options=options, providers=["CPUExecutionProvider"]
        )

    if "sung" not in forced_alignment._model_cache:
        forced_alignment._model_cache["sung"] = session(
            model_mirror.fetch(forced_alignment.SUNG_MODEL)
        )
    if "session" not in pitch_detection._fcpe_cache:
        pitch_detection._fcpe_cache["session"] = session(
            model_mirror.fetch(pitch_detection.FCPE_MODEL)
        )
    folder = game_notes.model_folder(str(cache))
    if folder not in game_notes._sessions:
        game_notes._sessions[folder] = {
            name: session(Path(folder) / f"{name}.onnx")
            for name in ("encoder", "estimator", "dur2bd", "bd2dur")
        }
    # The released diffusion segmenter draws random boundaries in each of its
    # eight steps. A fresh seeded session makes reprocessing the same recording
    # reproducible even when other songs were analysed earlier in this process.
    ort.set_seed(NOTE_SEED)
    game_notes._sessions[folder]["segmenter"] = session(Path(folder) / "segmenter.onnx")
    from huggingface_hub import hf_hub_download

    refiner_path = hf_hub_download(
        REFINER_REPO, "notefix.onnx", revision=REFINER_REV, local_files_only=True
    )
    return session(refiner_path)


def acoustic_evidence(notes, pitch):
    """Cross-check a note model against a separately estimated vocal fundamental."""
    import numpy as np

    times = np.asarray(pitch["times"])
    hz = np.asarray(pitch["frequencies"])
    voiced = hz > 0
    classes = np.full(len(hz), -1, dtype=int)
    classes[voiced] = np.rint(69 + 12 * np.log2(hz[voiced] / 440)).astype(int) % 12
    corroborated, comparisons = 0, 0
    regions = []
    for note in notes:
        left, right = np.searchsorted(times, [note["start"], note["end"]])
        evidence = classes[left:right]
        evidence = evidence[evidence >= 0]
        reasons = []
        if note.get("low_confidence"):
            reasons.append("alignment")
        if note.get("pitch") is None or not note.get("musical_support") or len(evidence) < 3:
            reasons.append("weak_vocal")
        else:
            same = int(np.sum(evidence == note["pitch"] % 12))
            corroborated += same
            comparisons += len(evidence)
            if same / len(evidence) < 0.6:
                reasons.append("pitch_disagreement")
        if reasons:
            regions.append(
                {"start": round(note["start"], 3), "end": round(note["end"], 3), "reasons": reasons}
            )
    return {
        "uncertain_notes": len(regions),
        "review_regions": regions,
        "pitch_consensus": round(corroborated / comparisons, 4) if comparisons else None,
    }


def chart_quality(voice, lyrics, language, cache):
    from services import forced_alignment, hyphenation, pitch_detection
    import soundfile as sf

    duration = sf.info(voice).duration
    if __package__:
        from .generation_assets.dense_alignment import align
    else:
        from generation_assets.dense_alignment import align
    refiner = configure_inference(cache)
    syllables = hyphenation.hyphenate_lyrics(lyrics, language)["hyphenated"]
    notify("Alineando sílabas y voz")
    pitch = pitch_detection.detect_pitches_fcpe(str(voice))
    try:
        timing, align_stats = align(forced_alignment, voice, syllables, pitch, language)
    except forced_alignment.AlignmentError as exc:
        raise ValueError("No se pudo alinear esta letra con la grabación.") from exc
    if not timing:
        raise ValueError("No se pudo alinear la letra con la voz.")
    notify("Calculando notas y prolongaciones")
    events = musical_events(voice, timing, cache, language)
    if not events:
        raise ValueError("No se detectó una melodía vocal que pueda convertirse en notas.")
    notes = join_syllables_and_notes(timing, events, pitch, duration)
    if __package__:
        from .generation_assets.pitch_refinement import refine
    else:
        from generation_assets.pitch_refinement import refine
    corrected = refine(notes, pitch, refiner)
    stats = {
        **align_stats,
        "refined_pitches": corrected,
        "syllables": len(timing),
        "musical_events": len(events),
        **acoustic_evidence(notes, pitch),
    }
    return notes, stats


def generate(args):
    import torch

    torch.set_num_threads(3)
    audio, output, cache = args.audio.resolve(), args.output.resolve(), args.cache.resolve()
    if not audio.is_file() or output.exists():
        raise ValueError("Se necesita un archivo de audio y una carpeta de salida nueva.")
    if args.lyrics and args.profile == "standard":
        raise ValueError("La alineación de una letra aportada requiere el perfil de alta calidad.")
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg") is None:
        raise ValueError("FFmpeg no está disponible en el entorno de Karaoke.")
    whisper, separator, pins = prepare(cache, args.profile, args.model_dir)
    with tempfile.TemporaryDirectory(prefix=".karaoke-chart-", dir=output.parent) as work:
        work = Path(work)
        payload = work / "package"
        payload.mkdir()
        notify("Separando la voz de la mezcla original")
        voice, duration = split_vocals(audio, work, separator)
        gc.collect()
        notify("Transcribiendo la letra")
        words, language = transcribe(voice, whisper, args.language)
        transcript = "\n".join(" ".join(w["word"] for w in spans) for spans in words)
        recognized_count = len(normalize(transcript).split())
        if not recognized_count:
            raise ValueError("No se reconoció una voz con letra suficiente para generar el mapa.")
        lyrics, source = transcript, {"kind": "asr"}
        if args.lyrics:
            if args.lyrics.stat().st_size > 160_000:
                raise ValueError("El texto de la letra excede el tamaño que admite el alineador.")
            lyrics = args.lyrics.read_text(encoding="utf-8-sig")
            size = len(normalize(lyrics).split())
            # Avoid forcing a complete libretto, or several repeats of a chorus, onto a single recording.
            agreement = (
                text_agreement(transcript, lyrics) if 0.25 <= size / recognized_count <= 3 else 0
            )
            if not size or (recognized_count >= 12 and agreement < 0.45):
                raise ValueError("La letra aportada parece corresponder a otra grabación.")
            source = {"kind": "user", "agreement": round(agreement, 3)}
        elif args.profile == "quality":
            selected = None
            if getattr(args, "captions", None):
                if __package__:
                    from .generation_assets.captions import matching_lyrics
                else:
                    from generation_assets.captions import matching_lyrics
                selected = matching_lyrics(
                    json.loads(args.captions.read_text(encoding="utf-8")), words, language
                )
            if selected is None and args.lookup_lyrics:
                selected = lookup(
                    transcript,
                    args.artist,
                    args.title,
                    duration,
                    rescue=lambda: recover_transcript(voice, whisper, language),
                )
            if selected:
                lyrics, source = selected
        if args.profile == "quality":
            notes, stats = chart_quality(voice, lyrics, language, cache)
        else:
            notify("Calculando la melodía vocal")
            notes, stats = standard_notes(voice, words), {}
        chart = payload / "song.txt"
        text = chart_text(notes, args.title, args.artist, language, duration)
        if source["kind"] == "lrclib" and language == "en":
            if __package__:
                from .generation_assets.spelling import restore_spelling
            else:
                from generation_assets.spelling import restore_spelling
            text, stats["spelling_corrections"] = restore_spelling(
                text, words, args.title, language
            )
        chart.write_text(text, encoding="utf-8")
        # Keep the artist's original vocal mix. Decode only when the source is not an MP3 stream.
        preserved = audio.suffix.lower() == ".mp3"
        if preserved:
            shutil.copyfile(audio, payload / "audio.mp3")
        else:
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-i",
                    str(audio),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-c:a",
                    "libmp3lame",
                    "-q:a",
                    "2",
                    str(payload / "audio.mp3"),
                ],
                check=True,
            )
        report = {
            "schema": 1,
            "state": "draft",
            "automatically_verified": False,
            "profile": args.profile,
            "method": "sung-ctc+free-game+fcpe" if args.profile == "quality" else "whisper-pyin",
            "language": language,
            "duration": duration,
            "lyrics": source,
            "models": pins,
            "input_sha256": digest(audio),
            "audio_sha256": digest(payload / "audio.mp3"),
            "chart_sha256": digest(chart),
            "chart": "song.txt",
            "audio": "audio.mp3",
            "notes": len(notes),
            "diagnostics": stats,
        }
        (payload / "generation.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        payload.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--profile", choices=("quality", "standard"), default="quality")
    parser.add_argument("--cache", type=Path, default=default_cache())
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--title")
    parser.add_argument("--artist")
    parser.add_argument("--language", choices=("auto", "es", "en"), default="auto")
    parser.add_argument("--lyrics", type=Path)
    parser.add_argument("--captions", type=Path)
    parser.add_argument("--lookup-lyrics", action="store_true")
    args = parser.parse_args()
    if not args.prepare and not all((args.audio, args.output, args.title, args.artist)):
        parser.error("Se necesitan --audio, --output, --title y --artist.")
    try:
        # Libraries may write logs to stdout. The caller receives exactly one JSON result there.
        with contextlib.redirect_stdout(sys.stderr):
            if args.prepare:
                _, _, pins = prepare(args.cache.resolve(), args.profile, args.model_dir)
                result = {
                    "schema": 1,
                    "profile": args.profile,
                    "state": "installed",
                    "models": pins,
                }
            else:
                result = generate(args)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    except (ValueError, OSError, RuntimeError, ImportError, subprocess.SubprocessError) as exc:
        print(
            json.dumps({"error": safe_text(str(exc), 500)}, ensure_ascii=False),
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    if __package__:
        from .generation_assets.runtime import configure_intel_openmp
    else:
        from generation_assets.runtime import configure_intel_openmp

    configure_intel_openmp()
    main()
