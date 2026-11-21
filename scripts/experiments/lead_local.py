"""Run the paired lead-vocal comparison on exact cached recordings, one model at a time.

All inference stays on the host. The caller controls when to start a stage. Failed stages
can resume from the persisted results of individual songs. No gold chart is opened.
"""

import argparse
import json
from pathlib import Path
import time

from lead_separation import digest, separate_center
from melody_transcribe import MODEL_SHA, infer, some_predictor


def write_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=("fcpe", "separate", "transcribe", "collect"))
    for name in (
        "manifest",
        "corpus",
        "stems",
        "output",
        "waves",
        "raw-results",
        "fcpe",
        "mdx",
        "source",
        "model",
    ):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--threads", type=int, default=3)
    p.add_argument("--device", default="mps")
    p.add_argument("--language", default="es")
    args = p.parse_args()
    cases = [v for v in json.loads(args.manifest.read_text()) if v["language"] == args.language]
    rows = {r["tag"]: r for r in json.loads(args.corpus.read_text())[args.language]}
    stems = json.loads(args.stems.read_text())
    args.waves.mkdir(parents=True, exist_ok=True)
    if args.stage == "fcpe":
        import numpy as np
        import onnxruntime as ort
        from lead_fcpe import contours, MODEL_SHA as fcpe_sha

        if digest(args.fcpe) != fcpe_sha:
            raise ValueError("Wrong FCPE model")
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = args.threads
        opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
        net = ort.InferenceSession(
            str(args.fcpe), sess_options=opts, providers=["CPUExecutionProvider"]
        )
    elif args.stage == "separate":
        from lead_mdx import open_model, separate
        import soundfile as sf

        net = open_model(args.mdx, args.threads)
    elif args.stage == "transcribe":
        if digest(args.model) != MODEL_SHA["some"]:
            raise ValueError("Wrong SOME model")
        net = some_predictor(args)

    for case in cases:
        tag = case["tag"]
        stem = Path(stems[tag])
        folder = args.output / tag
        folder.mkdir(parents=True, exist_ok=True)
        sha = digest(stem)
        if digest(rows[tag]["audio"]) != case["audio_sha"]:
            raise ValueError("Wrong original master " + tag)
        checkpoint = args.waves / (tag + ".json")
        start = time.monotonic()
        if args.stage == "fcpe":
            path = folder / "observations.npz"
            if path.is_file():
                with np.load(path) as previous:
                    if (
                        str(previous["source_sha"]) == sha
                        and str(previous["model_sha"]) == fcpe_sha
                    ):
                        continue
            raw, center = contours(stem, net)
            tmp = path.with_suffix(".tmp.npz")
            np.savez_compressed(
                tmp,
                raw=raw,
                center=center,
                model_sha=fcpe_sha,
                source_sha=sha,
                seconds=round(time.monotonic() - start, 3),
            )
            tmp.replace(path)
        elif args.stage == "separate":
            old = json.loads(checkpoint.read_text()) if checkpoint.is_file() else {}
            if old.get("stem_sha256") == sha and all(
                (args.waves / (tag + "." + name + ".wav")).is_file() for name in ("center", "mdx")
            ):
                continue
            meta = {
                "tag": tag,
                "stem_sha256": sha,
                "audio_sha256": case["audio_sha"],
                "master_pcm_sha256": case["pcm_sha256"],
                "source": "local",
                "frames": sf.info(stem).frames,
            }
            for name in ("center", "mdx"):
                target = args.waves / (tag + "." + name + ".wav")
                tmp = target.with_suffix(".tmp.wav")
                started = time.monotonic()
                if name == "center":
                    separate_center(stem, tmp)
                else:
                    separate(stem, tmp, net)
                if sf.info(tmp).frames != meta["frames"]:
                    raise ValueError("Changed source clock " + tag)
                tmp.replace(target)
                meta[name + "_seconds"] = round(time.monotonic() - started, 3)
            write_json(checkpoint, meta)
        elif args.stage == "transcribe":
            meta = json.loads(checkpoint.read_text())
            if meta["stem_sha256"] != sha:
                raise ValueError("Wrong derived recording")
            for name in ("all_vocals", "center", "mdx"):
                target = folder / (name + ".json")
                settings = dict(
                    stem_sha256=sha,
                    some_sha256=MODEL_SHA["some"],
                    model=name,
                    device=args.device,
                    core=18,
                    pad=2,
                )
                if name == "all_vocals":
                    settings["input_file_sha256"] = sha
                if target.is_file() and json.loads(target.read_text())["settings"] == settings:
                    continue
                reuse = False
                if name == "all_vocals":
                    cached = args.raw_results / (tag + ".json")
                    original = json.loads(cached.read_text()) if cached.is_file() else {}
                    prior = original.get("settings", {})
                    reuse = (
                        prior.get("source") == str(stem)
                        and prior.get("input_file_sha256") == sha
                        and prior.get("core") == 18
                        and prior.get("pad") == 2
                        and prior.get("device") == args.device
                        and prior.get("model_sha256") == MODEL_SHA["some"]
                    )
                if reuse:
                    events, elapsed = original["events"], original["seconds"]
                else:
                    src = stem if name == "all_vocals" else args.waves / (tag + "." + name + ".wav")
                    started = time.monotonic()
                    events = infer(src, net, 18, 2)
                    elapsed = round(time.monotonic() - started, 3)
                write_json(
                    target,
                    dict(
                        settings=settings,
                        events=events,
                        seconds=elapsed,
                        separation_s=meta.get(name + "_seconds", 0),
                    ),
                )
        else:
            import numpy as np
            from lead_fcpe import MODEL_SHA as fcpe_sha

            meta = json.loads(checkpoint.read_text())
            if meta["stem_sha256"] != sha:
                raise ValueError("Stale recording " + tag)
            with np.load(folder / "observations.npz") as obs:
                if str(obs["source_sha"]) != sha or str(obs["model_sha"]) != fcpe_sha:
                    raise ValueError("Stale FCPE result " + tag)
            for name in ("all_vocals", "center", "mdx"):
                pred = json.loads((folder / (name + ".json")).read_text())["settings"]
                if pred["stem_sha256"] != sha or pred["some_sha256"] != MODEL_SHA["some"]:
                    raise ValueError("Stale SOME result " + tag)
            write_json(folder / "provenance.json", meta)
        print(args.stage, tag, round(time.monotonic() - start, 2), flush=True)


if __name__ == "__main__":
    main()
