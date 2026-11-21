"""Offline research benchmark. Run with the isolated dependencies in the validation report."""

import argparse
import json
from math import gcd
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.ndimage import median_filter
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from karaoke.songs import read_chart, validate  # noqa: E402


@dataclass
class Note:
    start: float
    end: float
    pitch: int | None
    text: str


TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
ROW = re.compile(r"^([:*FRG])\s+(-?\d+)\s+(\d+)\s+(-?\d+) (.*)$")


def transcribe(vocals, model, language):
    samples, sr = sf.read(vocals, dtype="float32", always_2d=True)
    factor = gcd(16000, sr)
    waveform = resample_poly(samples.mean(axis=1), 16000 // factor, sr // factor)
    segments, _ = model.transcribe(
        waveform,
        language=language,
        word_timestamps=True,
        beam_size=5,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    return [
        [dict(word=w.word, start=w.start, end=w.end) for w in segment.words or []]
        for segment in segments
    ]


def make_chart(out, words):
    import parselmouth

    voice, sr = sf.read(out / "voice.wav", always_2d=True)
    # Praat estimates a monophonic fundamental on the separated vocal stem.
    pitch = parselmouth.Sound(voice.mean(axis=1), sampling_frequency=sr).to_pitch_ac(
        time_step=0.01, pitch_floor=70, pitch_ceiling=880
    )
    freq = pitch.selected_array["frequency"]
    midi = np.full(len(freq), -1000)
    voiced = freq > 0
    midi[voiced] = np.rint(69 + 12 * np.log2(freq[voiced] / 440)).astype(int)
    midi = median_filter(midi, size=7, mode="nearest")
    times = pitch.xs()

    # A 25 ms chart grid. Only sustained runs of four or more F0 frames create notes.
    # Start new lines on recognition segment boundaries, long pauses or eight words.
    lines = ["#TITLE:Borrador local", "#ARTIST:Ensayo", "#MP3:mix.wav", "#BPM:600", "#GAP:0"]
    last_end = 0
    for segment in words:
        line_words = 0
        for w in segment:
            word = w["word"].strip()
            if not TOKEN.search(word) or w["end"] <= w["start"]:
                continue
            first, stop = np.searchsorted(times, (w["start"], w["end"]))
            part = midi[first:stop]
            edges = np.r_[0, np.flatnonzero(np.diff(part)) + 1, len(part)]
            runs = []
            for a, b in zip(edges[:-1], edges[1:]):
                if b - a >= 4 and part[a] != -1000:
                    runs.append((times[first + a], times[first + b - 1] + 0.01, int(part[a] - 60)))
            if not runs:
                # Preserve the transcription, but do not score an unsupported pitch.
                runs.append((w["start"], w["end"], None))
            first_beat = round(runs[0][0] * 40)
            if last_end and (not line_words or line_words == 8 or first_beat - last_end >= 30):
                lines.append(f"- {last_end}")
                line_words = 0
            line_words += 1
            for i, (s, e, p) in enumerate(runs):
                start = max(last_end, round(s * 40))
                end = max(start + 1, round(e * 40))
                token = word if i == 0 else "~"
                space = " " if i == len(runs) - 1 else ""
                lines.append(
                    f"{'F' if p is None else ':'} {start} {end - start} {p or 0} {token}{space}"
                )
                last_end = end
    chart = out / "draft.txt"
    chart.write_text("\n".join([*lines, "E", ""]), encoding="utf-8")
    validate(chart)
    return chart


def extract(chart):
    text, meta = read_chart(chart)
    tick = 15 / float(meta["BPM"].replace(",", "."))
    gap = float(meta.get("GAP", "0").replace(",", ".")) / 1000
    notes, chars, onsets = [], [], []
    for line in text.splitlines():
        m = ROW.match(line)
        if m:
            kind, s, d, p, lyric = m.groups()
            start = gap + int(s) * tick
            note = Note(start, start + int(d) * tick, int(p) if kind in ":*" else None, lyric)
            notes.append(note)
            clean = unicodedata.normalize("NFKC", lyric.casefold()).replace("~", "")
            chars.append(clean)
            onsets.extend([start] * len(clean))
        elif line.startswith("-"):
            chars.append(" ")
            onsets.append(0)
    words = [(w.group(), onsets[w.start()]) for w in TOKEN.finditer("".join(chars))]
    return notes, words


def compare_words(ref, hyp):
    # Sequence alignment, never estimating a time shift from the reference.
    a, b = len(ref), len(hyp)
    cost = np.empty((a + 1, b + 1), dtype=int)
    cost[:, 0], cost[0, :] = np.arange(a + 1), np.arange(b + 1)
    for i in range(1, a + 1):
        for j in range(1, b + 1):
            c = ref[i - 1][0] != hyp[j - 1][0]
            cost[i, j] = min(cost[i - 1, j] + 1, cost[i, j - 1] + 1, cost[i - 1, j - 1] + c)
    i, j = a, b
    errors, matched_times = [], []
    while i or j:
        equal = i and j and ref[i - 1][0] == hyp[j - 1][0]
        if i and j and cost[i, j] == cost[i - 1, j - 1] + (not equal):
            if equal:
                delta = hyp[j - 1][1] - ref[i - 1][1]
                errors.append(abs(delta))
                matched_times.append((ref[i - 1][1], delta))
            i, j = i - 1, j - 1
        elif i and cost[i, j] == cost[i - 1, j] + 1:
            i -= 1
        else:
            j -= 1
    # Per-third medians expose time drift hidden by aggregate percentiles.
    bounds = np.linspace(ref[0][1], ref[-1][1] + 1e-6, 4)
    thirds = [[d for t, d in matched_times if lo <= t < hi] for lo, hi in zip(bounds, bounds[1:])]
    return dict(
        ref_words=a,
        hyp_words=b,
        edits=int(cost[a, b]),
        wer=round(cost[a, b] / a, 4),
        exact=len(errors),
        word_mae_p50_p90_s=np.round(np.percentile(errors, [50, 90]), 3).tolist() if errors else [],
        signed_word_p50_by_third_s=[
            round(float(np.median(ds)), 3) if ds else None for ds in thirds
        ],
    )


def compare_notes(ref, hyp):
    # Reference frames with a scored melody provide the denominator, including missed frames.
    frames = np.arange(0, max(ref[-1].end, hyp[-1].end) + 0.01, 0.01)

    def paint(notes):
        track = np.full(len(frames), -1)
        for n in notes:
            if n.pitch is not None:
                a, b = np.searchsorted(frames, [n.start, n.end])
                track[a:b] = n.pitch % 12
        return track

    gold, found = paint(ref), paint(hyp)
    scored = gold >= 0
    overlap = scored & (found >= 0)
    distance = abs(gold - found)
    exact = scored & (found == gold)
    within = overlap & (np.minimum(distance, 12 - distance) <= 1)
    # Count each onset at most once. Matching requires both a 100 ms window and
    # the same pitch class. Within each class the onsets are chronological.
    matches = 0
    for pitch_class in range(12):

        def starts(notes):
            return [n.start for n in notes if n.pitch is not None and n.pitch % 12 == pitch_class]

        reference, generated = starts(ref), starts(hyp)
        i = j = 0
        while i < len(reference) and j < len(generated):
            if reference[i] < generated[j] - 0.1:
                i += 1
            elif generated[j] < reference[i] - 0.1:
                j += 1
            else:
                i += 1
                j += 1
                matches += 1
    total = sum(n.pitch is not None for n in ref) + sum(n.pitch is not None for n in hyp)
    return dict(
        reference_notes=sum(n.pitch is not None for n in ref),
        generated_scored=sum(n.pitch is not None for n in hyp),
        generated_freestyle=sum(n.pitch is None for n in hyp),
        covered_frames=round(overlap.sum() / scored.sum(), 4),
        correct_class_all=round(exact.sum() / scored.sum(), 4),
        within_one_semitone_all=round(within.sum() / scored.sum(), 4),
        correct_when_covered=round(exact.sum() / overlap.sum(), 4) if overlap.any() else None,
        matching_onsets=matches,
        onset_pitch_f1_100ms=round(2 * matches / total, 4) if total else None,
    )


def benchmark(audio, language, model_dir, out):
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model
    from faster_whisper import WhisperModel

    out.mkdir(parents=True, exist_ok=False)
    times = {}
    start = time.perf_counter()
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(audio),
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "pcm_f32le",
            str(out / "mix.wav"),
        ],
        check=True,
    )
    times["decode"] = time.perf_counter() - start
    start = time.perf_counter()
    torch.set_num_threads(4)
    model = get_model("htdemucs").eval()
    times["load_separator"] = time.perf_counter() - start
    start = time.perf_counter()
    x, sr = sf.read(out / "mix.wav", dtype="float32", always_2d=True)
    wav = torch.from_numpy(x.T.copy())
    mono = wav.mean(0)
    mean, std = mono.mean(), mono.std()
    with torch.inference_mode():
        stems = apply_model(
            model,
            ((wav - mean) / std)[None],
            device="cpu",
            shifts=0,
            overlap=0.25,
            split=True,
            progress=False,
            num_workers=0,
        )
    vocals = stems[0, model.sources.index("vocals")] * std + mean
    sf.write(out / "voice.wav", vocals.T.numpy(), sr, subtype="FLOAT")
    times["separation"] = time.perf_counter() - start
    start = time.perf_counter()
    asr = WhisperModel(str(model_dir), device="cpu", compute_type="int8", cpu_threads=4)
    times["load_asr"] = time.perf_counter() - start
    start = time.perf_counter()
    words = transcribe(out / "voice.wav", asr, language)
    times["asr"] = time.perf_counter() - start
    start = time.perf_counter()
    draft = make_chart(out, words)
    times["chart_validate"] = time.perf_counter() - start
    return draft, {k: round(v, 3) for k, v in times.items()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("audio", type=Path)
    p.add_argument("language")
    p.add_argument("model_dir", type=Path)
    p.add_argument("output", type=Path, help="A new private scratch directory for the local song")
    p.add_argument("--reference", type=Path, help="Independent evaluation after generation")
    args = p.parse_args()
    draft, times = benchmark(args.audio, args.language, args.model_dir, args.output)
    report = {"seconds": times}
    if args.reference:
        ref, words = extract(args.reference)
        gen, recognized = extract(draft)
        report.update(compare_words(words, recognized), **compare_notes(ref, gen))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
