"""Guard research claims against stale bytes, missing songs, and overlong scored notes."""

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/experiments/evaluate_generation_candidate.py"
SPEC = importlib.util.spec_from_file_location("candidate_evaluation", SCRIPT)
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


def chart(*, length=20, wrong_first_pitch=False, extra_note=False):
    # One-second spacing, half-second notes, 25 ms ticks; no reference fitting is needed.
    lines = ["#TITLE:Fixture", "#ARTIST:Test", "#BPM:600", "#GAP:0"]
    for i in range(12):
        pitch = 1 if i == 0 and wrong_first_pitch else i % 5
        lines.append(f": {i * 40} {length} {pitch} word{i} ")
    if extra_note:
        lines.append(": 1000 20 0 outside ")
    return "\n".join([*lines, "E", ""])


@pytest.fixture
def cohort(tmp_path):
    identities, corpus, candidates = [], [], {}
    for i in range(40):
        tag = f"song-{i:02}"
        folder = tmp_path / tag
        folder.mkdir()
        audio, gold, predicted = folder / "audio.wav", folder / "gold.txt", folder / "draft.txt"
        audio.write_bytes(b"frozen master " + str(i).encode())
        gold.write_text(chart())
        predicted.write_text(chart())
        identity = {
            "tag": tag,
            "language": "es" if i < 20 else "en",
            "audio_sha": evaluation.digest(audio),
            "chart_sha": evaluation.digest(gold),
        }
        identities.append(identity)
        corpus.append({**identity, "audio": str(audio), "reference": str(gold), "duration": 20})
        candidates[tag] = str(predicted)
    identity_file = tmp_path / "identities.json"
    corpus_file = tmp_path / "corpus.json"
    candidate_file = tmp_path / "candidates.json"
    for path, value in ((identity_file, identities), (corpus_file, corpus), (candidate_file, candidates)):
        path.write_text(json.dumps(value))
    return {
        "identities": identity_file,
        "corpus": corpus_file,
        "candidates": candidate_file,
        "rows": corpus,
        "paths": candidates,
        "frozen": tmp_path / "frozen.json",
    }


def freeze(cohort):
    frozen = evaluation.freeze(
        cohort["candidates"], cohort["corpus"], cohort["identities"], "test candidate", "revision"
    )
    evaluation.write_new(cohort["frozen"], frozen)
    return frozen


def test_freezing_does_not_open_reference_contents(cohort):
    reference = Path(cohort["rows"][0]["reference"])
    reference.unlink()
    freeze(cohort)
    with pytest.raises(ValueError, match="missing reference"):
        evaluation.evaluate(cohort["frozen"])
    reference.write_text(chart())
    report = evaluation.evaluate(cohort["frozen"], near_perfect=True)
    assert report["summary"]["passes_five_gates"] == 40
    assert report["summary"]["meets_near_perfect_research_target"] == 40
    assert "not an unseen holdout" in report["cohort_note"]
    saved = cohort["frozen"].with_name("evaluation.json")
    evaluation.write_new(saved, report)
    assert json.loads(saved.read_text())["recordings"][0]["passes_five_gates"] is True


@pytest.mark.parametrize("source", ["audio", "reference", "candidate"])
def test_changed_master_reference_or_prediction_invalidates_evaluation(cohort, source):
    frozen = freeze(cohort)
    changed = Path(frozen["entries"][0][source]["path"])
    with changed.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match=f"Changed or missing {source}"):
        evaluation.evaluate(cohort["frozen"])


def test_missing_predictions_stay_in_full_cohort_denominator(cohort):
    Path(cohort["paths"]["song-00"]).unlink()
    freeze(cohort)
    report = evaluation.evaluate(cohort["frozen"], near_perfect=True)
    summary = report["summary"]
    assert summary["missing_count"] == 1
    assert summary["evaluated_count"] == 39
    assert summary["passes_five_gates"] == 39
    assert summary["five_gate_fraction_of_full_cohort"] == 39 / 40
    assert summary["near_perfect_fraction_of_full_cohort"] == 39 / 40
    assert summary["by_language"]["es"] == {"total": 20, "passes_five_gates": 19}


def test_right_pitch_and_attack_do_not_hide_notes_held_into_silence(cohort):
    Path(cohort["paths"]["song-00"]).write_text(chart(length=36))
    freeze(cohort)
    report = evaluation.evaluate(cohort["frozen"], near_perfect=True)
    song = report["recordings"][0]
    assert song["passes_initial_four_gates"] is True
    assert song["passes_five_gates"] is False
    assert song["meets_near_perfect_research_target"] is False
    assert song["metrics"]["scored_frame_precision"] < 0.6
    assert song["metrics"]["matched_offset_p50_p90_seconds"] == [0.4, 0.4]
    assert song["metrics"]["onset_pitch_offset_f1"] == 0


def test_near_perfect_target_is_stricter_than_current_five_gates(cohort):
    Path(cohort["paths"]["song-00"]).write_text(chart(wrong_first_pitch=True))
    freeze(cohort)
    report = evaluation.evaluate(cohort["frozen"], near_perfect=True)
    song = report["recordings"][0]
    assert song["passes_five_gates"] is True
    assert song["meets_near_perfect_research_target"] is False
    assert report["summary"]["passes_five_gates"] == 40
    assert report["summary"]["meets_near_perfect_research_target"] == 39


def test_out_of_recording_notes_are_failed_instead_of_clipped(cohort):
    Path(cohort["paths"]["song-00"]).write_text(chart(extra_note=True))
    freeze(cohort)
    report = evaluation.evaluate(cohort["frozen"])
    assert report["recordings"][0]["status"] == "invalid_timeline"
    assert report["summary"]["invalid_count"] == 1
    assert report["summary"]["five_gate_fraction_of_full_cohort"] == 39 / 40


def test_existing_results_cannot_be_reused_as_a_new_run(cohort):
    freeze(cohort)
    with pytest.raises(FileExistsError):
        freeze(cohort)
