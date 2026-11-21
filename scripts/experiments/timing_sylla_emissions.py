"""Measure foreground/background singing evidence in the exact mixture; never open chart text."""

import argparse
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import subprocess
import time

import numpy as np

REPO = "radiant-lyrics/sylla-600m-v1"
REVISION = "0a228acf0c1351ad0e2734604ee921d497d861e8"
LEAD_SHA = "bc8d8e504eabec5538027623b376e3f560691c2fb134c1a8fc6081bd10e86716"
BG_SHA = "c6d939babc45e1770a9bdd7d12a811eecf7fcd82006163c50cd343d0856f7e9f"
RATE = 16000
HOP = 320


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def tiled_attention(
    layer,
    hidden_states,
    attention_mask=None,
    relative_position_embeddings=None,
    output_attentions=False,
):
    """The same relative-key softmax in query tiles; never allocate T×T×head_size positional vectors."""
    import torch

    if layer.position_embeddings_type != "relative_key" or output_attentions or layer.training:
        raise ValueError("This route only implements the fixed Sylla relative-key inference model")
    batch, length, width = hidden_states.shape

    def project(fn):
        return (
            fn(hidden_states)
            .reshape(batch, length, layer.num_heads, layer.head_size)
            .transpose(1, 2)
        )

    query, key, value = project(layer.linear_q), project(layer.linear_k), project(layer.linear_v)
    keys = torch.arange(length, device=hidden_states.device)
    tiles = []
    for first in range(0, length, 96):
        stop = min(first + 96, length)
        q = query[:, :, first:stop]
        offsets = (keys[None, :] - keys[first:stop, None]).clamp(
            -layer.left_max_position_embeddings, layer.right_max_position_embeddings
        ) + layer.left_max_position_embeddings
        # Every offset indexes one of 73 vectors shared across all time positions.
        # Compute its dot product once per query and gather the key's value.
        relative = (q @ layer.distance_embedding.weight.T).gather(
            -1, offsets[None, None].expand(batch, layer.num_heads, -1, -1)
        )
        scores = (
            q @ key.transpose(-2, -1)
        ) / layer.head_size**0.5 + relative / layer.head_size**0.5
        if attention_mask is not None:
            scores = scores + attention_mask[:, :, first:stop, :]
        tiles.append(torch.softmax(scores, dim=-1) @ value)
    return layer.linear_out(
        torch.cat(tiles, dim=2).transpose(1, 2).reshape(batch, length, width)
    ), None


class Heads:
    def __init__(self, directory, device):
        from safetensors.torch import load_file
        from transformers import SeamlessM4TFeatureExtractor, Wav2Vec2BertForCTC
        import torch

        if (
            digest(directory / "model.safetensors") != LEAD_SHA
            or digest(directory / "bg_head.safetensors") != BG_SHA
        ):
            raise ValueError("Unexpected Sylla weights")
        self.torch = torch
        self.device = device
        self.dtype = torch.float32 if device == "cpu" else torch.float16
        self.network = (
            Wav2Vec2BertForCTC.from_pretrained(directory, local_files_only=True, dtype=self.dtype)
            .eval()
            .to(device)
        )
        self.features = SeamlessM4TFeatureExtractor.from_pretrained(
            directory, local_files_only=True
        )
        self.bg = {
            k: v.to(device=device, dtype=self.dtype)
            for k, v in load_file(directory / "bg_head.safetensors").items()
        }
        vocab = json.loads((directory / "vocab.json").read_text())
        # Keep all Latin letters registered by the model plus digits, blank and delimiter.
        # Full-vocabulary normalization happens before selecting these columns.
        self.labels = [
            "<blank>",
            "|",
            "'",
            *sorted(c for c in vocab if len(c) == 1 and c.isalnum() and ord(c) < 0x250),
        ]
        self.ids = torch.tensor([vocab[c] for c in self.labels], dtype=torch.long, device=device)

    def window(self, audio):
        torch = self.torch
        inputs = self.features(audio, sampling_rate=RATE, return_tensors="pt")
        features = inputs.input_features.to(self.device, self.dtype)
        mask = inputs.attention_mask.to(self.device)
        with torch.inference_mode():
            hidden = self.network.wav2vec2_bert(features, attention_mask=mask).last_hidden_state
            lead = self.network.lm_head(hidden)[0].float().log_softmax(-1)
            backing = (
                torch.nn.functional.linear(hidden, self.bg["weight"], self.bg["bias"])[0]
                .float()
                .log_softmax(-1)
            )
            pooled = torch.logaddexp(lead, backing) - np.log(2.0)
            return [x.index_select(-1, self.ids).half().cpu().numpy() for x in (lead, pooled)]

    def predict(self, audio):
        # A 24-s core with a real 2-s halo. Cropping uses the absolute 20-ms frame clock.
        padded = np.pad(audio, (2 * RATE, 2 * RATE + HOP * 2))
        length = (len(audio) + HOP - 1) // HOP
        heads = [[], []]
        for frame in range(0, length, 24 * RATE // HOP):
            count = min(length - frame, 24 * RATE // HOP)
            piece = padded[frame * HOP : (frame + count) * HOP + 4 * RATE]
            evidence = self.window(piece)
            for storage, windows in zip(heads, evidence, strict=True):
                crop = windows[100 : 100 + count]
                if len(crop) != count or not np.isfinite(crop).all():
                    raise ValueError("Sylla produced an incomplete window or non-finite logits")
                storage.append(crop)
        return tuple(np.concatenate(x) for x in heads)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Local recording IDs, paths and known SHA256s")
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--weights", type=Path, help="Pinned local weights (otherwise download once)"
    )
    parser.add_argument("--device", default="cpu", choices=("cuda", "cpu"))
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--device-lock", type=Path)
    args = parser.parse_args()
    import torch

    torch.set_num_threads(args.threads)
    if args.device_lock:
        from timing_neural import device_slot
    weights = args.weights
    if not weights:
        from huggingface_hub import snapshot_download

        weights = Path(snapshot_download(REPO, revision=REVISION))
    with device_slot(args.device_lock) if args.device_lock else nullcontext():
        model = Heads(weights, args.device)
    args.output.mkdir(parents=True, exist_ok=True)
    for item in json.loads(args.manifest.read_text()):
        output = args.output / (item["tag"] + ".npz")
        if output.is_file():
            continue
        audio = Path(item["audio"])
        if digest(audio) != item["audio_sha"]:
            raise ValueError("Unexpected recording for " + item["tag"])
        raw = subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(audio),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(RATE),
                "-f",
                "f32le",
                "-",
            ]
        )
        pcm = np.frombuffer(raw, dtype="<f4").copy()
        with device_slot(args.device_lock) if args.device_lock else nullcontext():
            started = time.monotonic()
            lead, pooled = model.predict(pcm)
            seconds = time.monotonic() - started
        temp = output.with_suffix(".tmp.npz")
        np.savez_compressed(
            temp,
            lead=lead,
            pooled=pooled,
            labels=model.labels,
            model_sha256=LEAD_SHA,
            bg_sha256=BG_SHA,
            audio_sha256=item["audio_sha"],
            device=args.device,
            seconds=seconds,
        )
        temp.replace(output)
        print(item["tag"], len(lead), round(seconds, 2), flush=True)


if __name__ == "__main__":
    main()
