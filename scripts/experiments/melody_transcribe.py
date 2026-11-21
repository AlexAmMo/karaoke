"""Infer musical events from isolated voices, without opening any lyric or reference chart."""

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import soundfile as sf


MODEL_SHA = {
    "some": "aa710fce920b4dae281b0e6cc2acba83345d82ee62d51f7bafeb29636f28f97c",
    "rosvot": "2b034b15126b21bd3f8ba7008f35aca51500f0443e5c36bdc85eba957c02ee38",
}


def load_file(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def some_predictor(args):
    """Load only inference modules, avoiding upstream training and web-app dependencies."""
    import torch
    import yaml

    source = args.source.resolve()
    sys.path.insert(0, str(source))
    from modules.model.Gmidi_conform import midi_conforms

    mel_class = load_file(source / "modules/rmvpe/spec.py", "some_mel").MelSpectrogram
    decode = load_file(source / "utils/infer_utils.py", "some_decode")
    config = yaml.safe_load(args.model.with_name("config.yaml").read_text())
    rate, hop = config["audio_sample_rate"], config["hop_size"]
    torch.set_num_threads(args.threads)
    device = torch.device(args.device)
    if device.type == "mps":
        torch.mps.set_per_process_memory_fraction(
            min(1.0, 2.5 * 1024**3 / torch.mps.recommended_max_memory())
        )
    model = midi_conforms(config).to(device).eval()
    state = torch.load(args.model, weights_only=True, map_location="cpu")["state_dict"]
    model.load_state_dict(
        {k.removeprefix("model."): v for k, v in state.items() if k.startswith("model.")}
    )
    mel = mel_class(
        config["units_dim"],
        rate,
        config["win_size"],
        hop,
        mel_fmin=config["fmin"],
        mel_fmax=config["fmax"],
    ).to(device)
    if device.type == "mps":
        # Upstream disables the math kernel for CUDA. MPS needs it. Use the same
        # attention operator and model weights with the backends supported here.
        from contextlib import nullcontext

        torch.backends.cuda.sdp_kernel = lambda **kwargs: nullcontext()

    @torch.inference_mode()
    def predict(audio, sample_rate):
        if sample_rate != rate:
            raise ValueError(f"SOME expects {rate} Hz; received {sample_rate}")
        features = mel(torch.from_numpy(audio.copy()).to(device)[None, :]).transpose(1, 2)
        zero = torch.zeros(features.shape[:2], device=device)
        mask = torch.ones_like(zero, dtype=torch.bool)
        probs, bounds = model(features, zero, mask, sig=True)
        # The reference decoder uses histogram scatter; these small tensors are
        # decoded on CPU so unsupported GPU scatter reductions cannot alter them.
        probs, bounds = probs.cpu(), bounds.cpu()
        alignment = decode.decode_bounds_to_alignment(bounds)
        midi, rest = decode.decode_gaussian_blurred_probs(
            probs,
            config["midi_min"],
            config["midi_max"],
            config["midi_prob_deviation"],
            config["rest_threshold"],
        )
        values, lengths, voiced = decode.decode_note_sequence(alignment, midi, ~rest)
        events = []
        frame = 0
        for note, length, sounding in zip(
            values[0].tolist(), lengths[0].tolist(), voiced[0].tolist()
        ):
            if sounding:
                events.append((frame * hop / rate, (frame + length) * hop / rate, round(note)))
            frame += length
        if device.type == "mps":
            torch.mps.empty_cache()
        return events

    return lambda windows, rate: (predict(audio, rate) for audio in windows)


def rosvot_predictor(args):
    import soxr

    def predict(windows, rate):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            output = directory / "result.json"
            names = []
            for i, audio in enumerate(windows):
                name = f"{i:05d}"
                names.append(name)
                signal = soxr.resample(audio, rate, 24000, quality="HQ") if rate != 24000 else audio
                sf.write(directory / f"{name}.wav", signal, 24000, subtype="PCM_24")
            subprocess.run(
                [
                    str(args.binary),
                    "--task",
                    "midi",
                    "--family",
                    "rosvot",
                    "--model",
                    str(args.model),
                    "--backend",
                    args.device,
                    "--threads",
                    str(args.threads),
                    "--batch-audio-dir",
                    str(directory),
                    "--batch-manifest-out",
                    str(output),
                    "--request-option",
                    "output_format=json",
                ],
                stdout=subprocess.DEVNULL,
                check=True,
            )
            rows = json.loads(output.read_text())["requests"]
            if [r["id"] for r in rows] != names:
                raise ValueError("ROSVOT dropped or reordered a window")
            for row in rows:
                notes = row["custom_schema_output"]["data"]["notes"]
                yield [(n["start"], n["end"], n["pitch"]) for n in notes if n["pitch"] > 0]

    return predict


def infer(wav, predict, core, pad):
    """Run overlapping windows; select each event by midpoint on the untrimmed clock."""
    result = []
    with sf.SoundFile(wav) as f:
        rate = f.samplerate
        windows = []
        for a in range(0, len(f), core * rate):
            b = min(len(f), a + core * rate)
            windows.append((a, b, max(0, a - pad * rate), min(len(f), b + pad * rate)))

        def samples():
            for _, _, left, right in windows:
                f.seek(left)
                yield f.read(right - left, dtype="float32", always_2d=True).mean(axis=1)

        for (a, b, left, _), events in zip(windows, predict(samples(), rate), strict=True):
            for start, end, pitch in events:
                start, end = max(0, start + left / rate), min(len(f) / rate, end + left / rate)
                if (
                    not 0 < pitch <= 127
                    or not a / rate <= (start + end) / 2 < b / rate
                    or end <= start
                ):
                    continue
                if result and start < result[-1][1]:
                    # Conflicting estimates at a seam are reconciled once on the
                    # original clock. Mid-window frames are never re-counted.
                    if pitch == result[-1][2]:
                        result[-1][1] = max(result[-1][1], end)
                        continue
                    if end <= result[-1][0]:
                        continue
                    boundary = (result[-1][1] + start) / 2
                    if boundary <= result[-1][0] or boundary >= end:
                        continue
                    result[-1][1] = start = boundary
                result.append([start, end, int(pitch)])
    return [[round(a, 6), round(b, 6), n] for a, b, n in result]


@contextmanager
def device_turn(path):
    if path is None:
        yield
        return
    import fcntl

    with path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("family", choices=MODEL_SHA)
    parser.add_argument("model", type=Path)
    parser.add_argument("stems", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", type=Path, help="OpenVPI SOME source checkout")
    parser.add_argument("--binary", type=Path, help="audio.cpp binary built with the rosvot family")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--device-lock", type=Path, help="Coordinate POSIX GPU workers per song")
    parser.add_argument("--threads", type=int, default=3)
    parser.add_argument("--core", type=int, default=18)
    parser.add_argument("--pad", type=int, default=2)
    parser.add_argument(
        "--expect",
        type=int,
        default=0,
        help="Follow expanding stem index until this many songs are finished",
    )
    args = parser.parse_args()
    with args.model.open("rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != MODEL_SHA[args.family]:
            raise ValueError("Unexpected checkpoint")
    if args.core <= 0 or args.pad < 0:
        parser.error("Invalid window duration")
    predict = None
    args.output.mkdir(parents=True, exist_ok=True)
    while True:
        sources = json.loads(args.stems.read_text())
        for tag, wav in sources.items():
            output = args.output / f"{tag}.json"
            config = dict(
                family=args.family,
                model_sha256=MODEL_SHA[args.family],
                core=args.core,
                pad=args.pad,
                device=args.device,
                source=str(wav),
            )
            if output.is_file() and json.loads(output.read_text())["settings"] == config:
                continue
            with device_turn(args.device_lock):
                if predict is None:
                    predict = (some_predictor if args.family == "some" else rosvot_predictor)(args)
                start = time.monotonic()
                events = infer(wav, predict, args.core, args.pad)
                seconds = round(time.monotonic() - start, 3)
            temp = output.with_suffix(".tmp")
            temp.write_text(json.dumps(dict(events=events, settings=config, seconds=seconds)))
            temp.replace(output)
            print(tag, len(events), seconds, flush=True)
        if len(sources) >= args.expect:
            return
        time.sleep(10)


if __name__ == "__main__":
    main()
