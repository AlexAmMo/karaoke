"""A frozen prediction can be rescored, but cannot stand in for different inputs."""

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/benchmark_generation_corpus.py"
SPEC = importlib.util.spec_from_file_location("generation_benchmark", SCRIPT)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)
GENERATE = benchmark.generate_predictions


@pytest.fixture
def cached(tmp_path, monkeypatch):
    audio, gold = tmp_path / "audio.wav", tmp_path / "gold.txt"
    audio.write_bytes(b"master recording")
    chart = "#TITLE:Song\n#ARTIST:Artist\n#BPM:600\n#GAP:0\n" + "\n".join(
        f": {i * 40} 20 {i % 5} word{i} " for i in range(12)
    ) + "\nE\n"
    gold.write_text(chart)
    row = {"tag": "song", "language": "es", "title": "Song", "artist": "Artist",
           "audio": str(audio), "reference": str(gold),
           "audio_sha": benchmark.worker.digest(audio), "chart_sha": benchmark.worker.digest(gold)}
    args = SimpleNamespace(manifest=tmp_path / "manifest.json", output=tmp_path / "output",
                           cache=tmp_path / "models", model_dir=None, clip_seconds=0,
                           lookup_lyrics=False, keep_stems=False)
    args.manifest.write_text(json.dumps([row]))
    folder = args.output / "song"
    folder.mkdir(parents=True)
    (folder / "draft.txt").write_text(chart)
    monkeypatch.setattr(benchmark, "seconds", lambda _: 20.0004)
    monkeypatch.setattr(benchmark, "generation_code", lambda _: {"revision": "generation-a"})
    monkeypatch.setattr(benchmark, "evaluation_code", lambda: {"revision": "evaluation-a"})

    def unexpected(*_args, **_kwargs):
        pytest.fail("Cached prediction must not run inference or prepare models")

    monkeypatch.setattr(benchmark, "generate_predictions", unexpected)
    monkeypatch.setattr(benchmark.worker, "prepare", unexpected)
    signature = benchmark.inputs_for(row, args, benchmark.generation_code(args))
    result = {"id": "song", "language": "es", "offset_s": 0, "duration_s": 20,
              "lyrics_source": {"kind": "asr"}, "seconds": {"chart": 5},
              "audio_sha256": row["audio_sha"],
              "draft_sha256": benchmark.worker.digest(folder / "draft.txt"), "diagnostics": {}}
    prediction = benchmark.seal({"signature": signature, "result": result,
                                 "duration_seconds": 20.0004})
    benchmark.save(folder / "prediction.json", prediction)
    return args, row, folder, prediction


def test_valid_cache_skips_scoring_and_model_preparation(cached, monkeypatch):
    args, _, folder, _ = cached
    benchmark.run(args)
    before = (folder / "metrics.json").read_bytes()
    monkeypatch.setattr(benchmark, "score", lambda *_: pytest.fail("Valid score should be reused"))
    benchmark.run(args)
    assert (folder / "metrics.json").read_bytes() == before


@pytest.mark.parametrize("changed", ["evaluator", "reference", "metrics"])
def test_metric_only_changes_reuse_prediction_without_inference(cached, monkeypatch, changed):
    args, row, folder, _ = cached
    benchmark.run(args)
    prediction_bytes = (folder / "prediction.json").read_bytes()
    if changed == "evaluator":
        monkeypatch.setattr(benchmark, "evaluation_code", lambda: {"revision": "evaluation-b"})
    elif changed == "reference":
        gold = Path(row["reference"])
        gold.write_text(gold.read_text().replace("word0 ", "different "))
        row["chart_sha"] = benchmark.worker.digest(gold)
        args.manifest.write_text(json.dumps([row]))
    else:
        report = json.loads((folder / "metrics.json").read_text())
        report["metrics"]["wer"] = .99
        (folder / "metrics.json").write_text(json.dumps(report))
    original_score = benchmark.score
    calls = []

    def rescore(*values):
        calls.append(values)
        return original_score(*values)

    monkeypatch.setattr(benchmark, "score", rescore)
    benchmark.run(args)
    assert len(calls) == 1
    assert calls[0][3] == 20.0004  # Retain the original unrounded evaluation window.
    assert (folder / "prediction.json").read_bytes() == prediction_bytes
    report = json.loads((folder / "metrics.json").read_text())
    assert benchmark.intact(report)
    assert report["metrics"]["wer"] == (round(1 / 12, 4) if changed == "reference" else 0)


@pytest.mark.parametrize("changed", ["audio", "window", "language", "generation", "draft"])
def test_changed_prediction_input_never_reuses_old_metrics(cached, monkeypatch, changed):
    args, row, folder, _ = cached
    benchmark.run(args)
    if changed == "audio":
        Path(row["audio"]).write_bytes(b"different recording")
        row["audio_sha"] = benchmark.worker.digest(row["audio"])
    elif changed == "window":
        args.clip_seconds = 10
    elif changed == "language":
        row["language"] = "en"
    elif changed == "generation":
        monkeypatch.setattr(benchmark, "generation_code", lambda _: {"revision": "generation-b"})
    else:
        (folder / "draft.txt").write_text("changed chart")
    args.manifest.write_text(json.dumps([row]))
    with pytest.raises(ValueError, match="new work directory"):
        benchmark.run(args)


def test_reference_hash_is_checked_even_when_metrics_exist(cached):
    args, row, _, _ = cached
    benchmark.run(args)
    Path(row["reference"]).write_text("changed gold without declared identity change")
    with pytest.raises(ValueError, match="evaluation reference changed"):
        benchmark.run(args)


def test_legacy_metrics_and_stale_acoustics_are_rejected_before_inference(cached):
    args, _, folder, prediction = cached
    (folder / "prediction.json").unlink()
    benchmark.save(folder / "metrics.json", {"meets_thresholds": True})
    with pytest.raises(ValueError, match="unversioned cache"):
        benchmark.run(args)
    (folder / "metrics.json").unlink()
    stage = {"signature": {**prediction["signature"], "language": "en"}, "words": []}
    benchmark.save(folder / "acoustics.json", benchmark.seal(stage))
    with pytest.raises(ValueError, match="acoustics changed"):
        benchmark.run(args)


def test_result_cohort_excludes_reports_outside_current_manifest(cached):
    args, _, _, _ = cached
    unrelated = args.output / "previous-song"
    unrelated.mkdir()
    benchmark.save(unrelated / "metrics.json", {"id": "previous-song", "meets_thresholds": True})
    benchmark.run(args)
    results = json.loads((args.output / "results.json").read_text())
    assert [row["id"] for row in results] == ["song"]


def test_new_prediction_is_frozen_before_evaluation_without_real_models(cached, monkeypatch):
    args, row, folder, _ = cached
    (folder / "prediction.json").unlink()
    chart = (folder / "draft.txt").read_text()
    (folder / "draft.txt").unlink()
    monkeypatch.setattr(benchmark, "generate_predictions", GENERATE)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda _: None))
    monkeypatch.setitem(sys.modules, "soundfile", SimpleNamespace(
        info=lambda _: SimpleNamespace(duration=20.0004)))
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(
        WhisperModel=lambda *_a, **_k: object()))
    monkeypatch.setattr(benchmark.worker, "prepare", lambda *_: ("asr", "separator", {}))

    def split(_audio, temporary, _model):
        voice = temporary / "vocals.wav"
        voice.write_bytes(b"synthetic stem")
        return voice, None

    monkeypatch.setattr(benchmark.worker, "split_vocals", split)
    monkeypatch.setattr(benchmark.worker, "transcribe", lambda *_a, **_k:
                        ([[{"word": f"word{i}"} for i in range(12)]], "es"))
    monkeypatch.setattr(benchmark.worker, "chart_quality", lambda *_: ([], {}))
    monkeypatch.setattr(benchmark.worker, "chart_text", lambda *_: chart)
    original = benchmark.score

    def score_after_freeze(*values):
        frozen = json.loads((folder / "prediction.json").read_text())
        assert benchmark.intact(frozen)
        assert "metrics" not in frozen["result"]
        return original(*values)

    monkeypatch.setattr(benchmark, "score", score_after_freeze)
    benchmark.run(args)
    stage = json.loads((folder / "acoustics.json").read_text())
    assert benchmark.intact(stage)
    assert stage["signature"]["audio_sha256"] == row["audio_sha"]
    assert json.loads((folder / "metrics.json").read_text())["meets_thresholds"] is True
