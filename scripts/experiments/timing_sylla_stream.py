"""Memory-bounded Sylla inference. Evaluate both heads with just one Transformer block on the GPU."""

import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import subprocess
from time import monotonic
from types import MethodType

import numpy as np

from timing_neural import device_slot
from timing_sylla_emissions import BG_SHA, HOP, LEAD_SHA, RATE, digest, tiled_attention


def windows(record, extractor):
    audio = Path(record["audio"])
    if digest(audio) != record["audio_sha"]:
        raise ValueError("Different recording for " + record["tag"])
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
    pcm = np.frombuffer(raw, dtype="<f4")
    padded = np.pad(pcm, (2 * RATE, 2 * RATE + HOP * 2))
    frames = (len(pcm) + HOP - 1) // HOP
    result = []
    for start in range(0, frames, 1200):
        count = min(1200, frames - start)
        audio = padded[start * HOP : (start + count) * HOP + 4 * RATE]
        info = extractor(audio, sampling_rate=RATE, return_tensors="np")
        result.append([info.input_features, info.attention_mask, count])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("weights", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--group", type=int, default=2)
    parser.add_argument("--device", choices=("cpu", "mps"), default="mps")
    parser.add_argument("--device-lock", type=Path)
    args = parser.parse_args()
    if args.group < 1:
        parser.error("--group must be positive")
    import torch
    from safetensors import safe_open
    from safetensors.torch import load_file
    from transformers import SeamlessM4TFeatureExtractor, Wav2Vec2BertConfig, Wav2Vec2BertForCTC

    if (
        digest(args.weights / "model.safetensors") != LEAD_SHA
        or digest(args.weights / "bg_head.safetensors") != BG_SHA
    ):
        raise ValueError("Sylla weights have changed")
    torch.set_num_threads(2)
    device = args.device
    dtype = torch.float16 if device == "mps" else torch.float32

    def barrier():
        if device == "mps":
            torch.mps.synchronize()
            torch.mps.empty_cache()

    def lock():
        return device_slot(args.device_lock) if args.device_lock else nullcontext()

    config = Wav2Vec2BertConfig.from_pretrained(args.weights, local_files_only=True)
    if (
        config.add_adapter
        or config.use_intermediate_ffn_before_adapter
        or config.position_embeddings_type != "relative_key"
    ):
        raise ValueError("Expected the Sylla v1 reference architecture")
    with torch.device("meta"):
        network = Wav2Vec2BertForCTC(config).eval()
    feat = SeamlessM4TFeatureExtractor.from_pretrained(args.weights, local_files_only=True)
    vocab = json.loads((args.weights / "vocab.json").read_text())
    labels = [
        "<blank>",
        "|",
        "'",
        *sorted(c for c in vocab if len(c) == 1 and c.isalnum() and ord(c) < 0x250),
    ]
    ids = torch.tensor([vocab[c] for c in labels], device=device)
    args.output.mkdir(exist_ok=True, parents=True)
    manifest = [
        r
        for r in json.loads(args.manifest.read_text())
        if not (args.output / (r["tag"] + ".npz")).exists()
    ]
    with (
        torch.inference_mode(),
        safe_open(args.weights / "model.safetensors", framework="pt") as source,
    ):

        def materialize(module, prefix):
            values = {
                name: source.get_tensor(prefix + "." + name).to(device=device, dtype=dtype)
                for name in module.state_dict()
            }
            module.load_state_dict(values, assign=True)

        first_layer = True
        for group in range(0, len(manifest), args.group):
            songs = manifest[group : group + args.group]
            started = monotonic()
            clips = [(row, windows(row, feat)) for row in songs]
            all_windows = [w for _, records in clips for w in records]
            projection = network.wav2vec2_bert.feature_projection
            with lock():
                materialize(projection, "wav2vec2_bert.feature_projection")
                for w in all_windows:
                    x = torch.from_numpy(w[0]).to(device=device, dtype=dtype)
                    mask = torch.from_numpy(w[1]).to(device=device).bool()
                    projected = projection(x)[0].masked_fill(~mask.unsqueeze(-1), 0.0)
                    w[0] = projected.cpu().numpy()
                del x, mask, projected
                projection.to_empty(device="meta")
                barrier()
            for i, layer in enumerate(network.wav2vec2_bert.encoder.layers):
                with lock():
                    materialize(layer, f"wav2vec2_bert.encoder.layers.{i}")
                    attention = layer.self_attn
                    # Compare against the upstream module before enabling a more
                    # compact, algebraically equivalent relative-position lookup.
                    if first_layer:
                        sample = (
                            torch.sin(
                                torch.arange(113 * 1024, device=device, dtype=torch.float32) / 37
                            )
                            .reshape(1, 113, 1024)
                            .to(dtype)
                        )
                        native = attention(sample)[0]
                        bounded = tiled_attention(attention, sample)[0]
                        if not torch.allclose(native, bounded, atol=0.006, rtol=0.006):
                            raise ValueError(
                                "The tiled attention implementation differs from upstream"
                            )
                        first_layer = False
                        del sample, native, bounded
                    attention.forward = MethodType(tiled_attention, attention)
                    for w in all_windows:
                        x = torch.from_numpy(w[0]).to(device=device, dtype=dtype)
                        mask = torch.from_numpy(w[1]).to(device=device)
                        additive = (1.0 - mask[:, None, None, :].to(dtype)) * torch.finfo(dtype).min
                        out = layer(
                            x,
                            attention_mask=additive.expand(1, 1, x.shape[1], x.shape[1]),
                            conv_attention_mask=mask,
                            output_attentions=False,
                        )[0]
                        w[0] = out.cpu().numpy()
                        del x, mask, additive, out
                    layer.to_empty(device="meta")
                    barrier()
                print(
                    "layer",
                    i + 1,
                    "of",
                    len(network.wav2vec2_bert.encoder.layers),
                    ",".join(r["tag"] for r in songs),
                    flush=True,
                )
            with lock():
                materialize(network.lm_head, "lm_head")
                bg = {
                    k: v.to(device=device, dtype=dtype)
                    for k, v in load_file(args.weights / "bg_head.safetensors").items()
                }
                for row, records in clips:
                    heads = [[], []]
                    for hidden, mask, count in records:
                        h = torch.from_numpy(hidden).to(device=device)
                        lead = network.lm_head(h)[0].float().log_softmax(-1)
                        other = (
                            torch.nn.functional.linear(h, bg["weight"], bg["bias"])[0]
                            .float()
                            .log_softmax(-1)
                        )
                        pooled = torch.logaddexp(lead, other) - np.log(2.0)
                        for storage, prob in zip(heads, (lead, pooled), strict=True):
                            crop = (
                                prob[100 : 100 + count].index_select(-1, ids).half().cpu().numpy()
                            )
                            if len(crop) != count or not np.isfinite(crop).all():
                                raise ValueError("Invalid probabilities")
                            storage.append(crop)
                    target = args.output / (row["tag"] + ".npz")
                    temporary = target.with_suffix(".tmp.npz")
                    np.savez_compressed(
                        temporary,
                        lead=np.concatenate(heads[0]),
                        pooled=np.concatenate(heads[1]),
                        labels=labels,
                        model_sha256=LEAD_SHA,
                        bg_sha256=BG_SHA,
                        audio_sha256=row["audio_sha"],
                        device=device,
                        group_size=len(clips),
                        group_seconds=monotonic() - started,
                    )
                    temporary.replace(target)
                    print("ready", row["tag"], flush=True)
                network.lm_head.to_empty(device="meta")
                del bg, lead, pooled, other, h
                barrier()


if __name__ == "__main__":
    main()
