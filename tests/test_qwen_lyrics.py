"""Measure ASR text without losing refrains, inventing timing, or dropping failures."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/experiments/qwen_lyrics.py"
SPEC = importlib.util.spec_from_file_location("qwen_lyrics", SCRIPT)
qwen = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qwen)


def chart():
    return "\n".join([
        "#TITLE:Fixture", "#ARTIST:Test", "#LANGUAGE:Spanish", "#BPM:600", "#GAP:0",
        ": 0 20 0 corazón ", ": 40 20 0 hola ", ": 80 20 0 hola ", ": 120 20 0 hola ", "E", "",
    ])


def test_normalized_text_keeps_repetitions_and_counts_missing_words():
    reference = [(word, float(i)) for i, word in enumerate(("corazón", "hola", "hola", "hola"))]
    words = qwen.transcript_words("¡CORAZO\u0301N! ｈｏｌａ, hola, HOLA.")
    assert [word for word, _ in words] == ["corazón", "hola", "hola", "hola"]
    exact = qwen.lyric_metrics(reference, words)
    assert exact == {"wer": 0.0, "edits": 0, "ref_words": 4, "hyp_words": 4}
    omitted = qwen.lyric_metrics(reference, qwen.transcript_words("corazón hola"))
    assert omitted == {"wer": 0.5, "edits": 2, "ref_words": 4, "hyp_words": 2}
    assert type(omitted["wer"]) is float
    assert type(omitted["edits"]) is int
    json.dumps(omitted)


@pytest.fixture
def corpus(tmp_path):
    identities, records = [], []
    predictions = tmp_path / "predictions"
    for i in range(40):
        tag = f"song-{i:02}"
        folder = tmp_path / tag
        folder.mkdir()
        audio, reference, baseline = folder / "audio.wav", folder / "gold.txt", folder / "draft.txt"
        audio.write_bytes(f"master {i}".encode())
        reference.write_text(chart())
        baseline.write_text(chart())
        identity = {"tag": tag, "language": "es", "audio_sha": qwen.digest(audio),
                    "chart_sha": qwen.digest(reference)}
        identities.append(identity)
        records.append({**identity, "audio": str(audio), "reference": str(reference)})
        if i < 2:
            output = predictions / tag
            output.mkdir(parents=True)
            text = "¡CORAZO\u0301N! ｈｏｌａ, hola, HOLA." if i == 0 else "corazón hola"
            (output / "lyrics.txt").write_text(text)
            qwen.write_json(output / "raw.json", {"transcription": [{"text": text}]})
            qwen.write_json(output / "frozen.json", {
                "signature": {"stem": str(audio), "stem_sha256": qwen.digest(audio),
                              "baseline": str(baseline), "baseline_sha256": qwen.digest(baseline),
                              "implementation_sha256": "existing-v0-evidence"},
                "text_sha256": qwen.digest(output / "lyrics.txt"),
                "raw_sha256": qwen.digest(output / "raw.json"), "seconds": 1,
            })
    args = SimpleNamespace(identities=tmp_path / "identities.json", corpus=tmp_path / "corpus.json",
                           predictions=predictions, output=tmp_path / "evaluation.json")
    args.identities.write_text(json.dumps(identities))
    args.corpus.write_text(json.dumps({"es": records}))
    return args


def test_evaluation_serializes_numpy_metrics_and_keeps_all_40_in_denominator(corpus, monkeypatch):
    monkeypatch.setattr(qwen.subprocess, "run", lambda *_a, **_k: pytest.fail("No inference"))
    frozen = corpus.predictions / "song-00/frozen.json"
    unchanged = frozen.read_bytes()
    qwen.evaluate(corpus)
    report = json.loads(corpus.output.read_text())
    assert report["cohort_size"] == 40
    assert report["measured"] == 2
    assert report["missing"] == 38
    assert report["wer_at_most_1_percent"] == 1
    assert report["fraction_of_full_cohort_at_most_1_percent"] == 1 / 40
    assert report["fraction_of_full_cohort_at_most_5_percent"] == 1 / 40
    assert report["median_wer"] == .25
    assert report["rows"][1]["wer"] == .5
    assert report["rows"][1]["edits"] == 2
    assert "Lyrics only" in report["scope"]
    assert len(report["evaluation_implementation_sha256"]) == 64
    assert frozen.read_bytes() == unchanged


def test_missing_candidate_does_not_skip_official_identity_validation(corpus):
    records = json.loads(corpus.corpus.read_text())
    records["es"][2]["audio_sha"] = "different master"
    corpus.corpus.write_text(json.dumps(records))
    with pytest.raises(ValueError, match="official master"):
        qwen.evaluate(corpus)


def test_evaluation_changes_do_not_change_generation_signature(monkeypatch):
    generation_before = qwen.generation_implementation()
    evaluation_before = qwen.evaluation_implementation()

    def revised_evaluate(_args):
        return "different evaluator"

    monkeypatch.setattr(qwen, "evaluate", revised_evaluate)
    assert qwen.generation_implementation() == generation_before
    assert qwen.evaluation_implementation() != evaluation_before


def test_generation_changes_invalidate_its_signature(monkeypatch):
    before = qwen.generation_implementation()

    def revised_generate(_args):
        return "different generator"

    monkeypatch.setattr(qwen, "generate", revised_generate)
    assert qwen.generation_implementation() != before
