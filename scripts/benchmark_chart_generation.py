"""Offline research benchmark. Run with the isolated dependencies in the validation report."""

import argparse
import json
from math import gcd
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.ndimage import median_filter
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from karaoke.generation_metrics import (  # noqa: E402
    TOKEN,
    compare_notes,
    compare_words,
    extract,
    ROW as ROW,
    Note as Note,
)
from karaoke.songs import read_chart as read_chart, validate  # noqa: E402


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
    from karaoke.generation_assets.runtime import configure_intel_openmp

    configure_intel_openmp()
    main()
