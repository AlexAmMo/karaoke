import hashlib
import re
from pathlib import Path

import pytest

from karaoke import generation_verification as verification
from karaoke.songs import SongError


def make_chart(path, *, gap=0, pitch=0, reorder=False):
    words = [f"syllable{i}" for i in range(42)]
    if reorder:
        words.reverse()
    lines = [f": {i * 4} 3 {i % 9 + pitch} {w} " for i, w in enumerate(words)]
    path.write_text("\n".join(["#ARTIST:A", "#TITLE:S", "#BPM:120", f"#GAP:{gap}", *lines, "E"]))
    return path


def test_only_the_matching_independent_recording_can_promote_a_prediction(tmp_path, monkeypatch):
    gold = make_chart(tmp_path / "reference.txt")
    draft = make_chart(tmp_path / "draft.txt")
    media = tmp_path / "media"
    media.write_bytes(b"test recording")
    song = {
        "video_id": "0123456789a",
        "tracks": 1,
        "reference_duration": 24,
        "source": "allkaraoke:aa",
    }
    rows = [song]
    monkeypatch.setattr(verification.allkaraoke, "search", lambda *a, **k: rows)
    monkeypatch.setattr(verification.allkaraoke, "load_chart", lambda *a: gold)
    monkeypatch.setattr(verification.acoustic, "require_alignment", lambda chart, audio: None)

    def verify():
        return verification.verify_generated(draft, media, 24, "0123456789a", tmp_path)

    assert verify()["chart_sha256"] == hashlib.sha256(draft.read_bytes()).hexdigest()
    for change in (dict(gap=350), dict(pitch=2), dict(reorder=True)):
        make_chart(draft, **change)
        assert verify() is None
    make_chart(draft)
    for mismatch in (dict(video_id="x123456789a"), dict(tracks=2), dict(reference_duration=27)):
        rows[:] = [{**song, **mismatch}]
        assert verify() is None
    rows[:] = [song, song]
    assert verify() is None
    rows[:] = [song]

    def reject(chart, audio):
        assert chart == gold and audio == media
        raise SongError("Unreliable recording")

    monkeypatch.setattr(verification.acoustic, "require_alignment", reject)
    assert verify() is None


def test_unverified_map_stays_out_of_queue_and_verified_one_keeps_its_turn(tmp_path, package):
    import json
    import shutil
    from concurrent.futures import Future
    from karaoke.service import Service
    from karaoke.songs import validate

    host = Service(tmp_path / "room")
    try:
        uid = host.lab.enqueue("0123456789a", "Song", "Artist", "en", "quality")
        dest = host.lab.root / uid / "draft"
        shutil.copytree(package.parent, dest)
        chart = dest / "song.txt"
        audio = validate(chart)["audio"]
        with open(audio, "rb") as stream:
            audio_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        chart_hash = hashlib.sha256(chart.read_bytes()).hexdigest()
        (dest / "generation.json").write_text(json.dumps({"chart_sha256": chart_hash}))
        chart.with_name("verified.txt").write_bytes(chart.read_bytes())
        evidence = dict(
            generated_sha256=chart_hash,
            chart_sha256=chart_hash,
            audio_sha256=audio_hash,
            video_id="0123456789a",
        )
        src = "allkaraoke:fixture"
        turn = host.store.request(src, {"kind": "allkaraoke"}, ["Luna"])
        host.store.execute("INSERT INTO draft_turns VALUES(?,?,?)", (uid, turn, src))

        def finish(result):
            host.store.execute("UPDATE drafts SET state='working' WHERE id=?", (uid,))
            host.lab.current = uid
            host.lab.future = Future()
            host.lab.future.set_result(result)
            host.lab.tick()

        finish({**evidence, "audio_sha256": "changed"})
        assert host.lab.row(uid)["state"] == "review" and host.store.queue()[0]["song_id"] is None
        assert not list(host.library.glob("*/song.txt"))
        finish(evidence)
        row = host.lab.row(uid)
        saved = host.store.queue()[0]
        assert row["state"] == "approved"
        assert (
            saved["song_id"] == row["song_id"] and saved["id"] == turn and "Luna" in saved["names"]
        )
        info = Path(host.song(row["song_id"])["chart"]).with_name("generation.json")
        proof = json.loads(info.read_text())
        assert proof["automatically_verified"] and proof["state"] == "verified"
        assert host.lab.approve(uid) == row["song_id"]
    finally:
        host.close()


def test_generated_sustains_do_not_score_the_silences_in_an_independent_map(tmp_path, monkeypatch):
    gold = make_chart(tmp_path / "reference.txt")
    draft = tmp_path / "song.txt"
    text = gold.read_text()
    draft.write_text(re.sub(r"(?m)^(: -?\d+) 3 ", r"\1 4 ", text))
    original = draft.read_bytes()
    verified = tmp_path / "verified.txt"
    media = tmp_path / "recording"
    media.write_bytes(b"exact recording")
    song = {
        "source": "allkaraoke:one",
        "video_id": "0123456789a",
        "tracks": 1,
        "reference_duration": 24,
    }
    monkeypatch.setattr(verification.allkaraoke, "search", lambda *a, **k: [song])
    monkeypatch.setattr(verification.allkaraoke, "load_chart", lambda *a: gold)
    monkeypatch.setattr(verification.acoustic, "require_alignment", lambda *a: None)
    proof = verification.verify_generated(
        draft, media, 24, song["video_id"], tmp_path, verified_chart=verified
    )
    assert (
        proof["scoring"] == "confirmed_intervals"
        and proof["raw_metrics"]["scored_frame_precision"] < 0.8
    )
    assert proof["metrics"]["scored_frame_precision"] == proof["metrics"]["correct_class_all"] == 1
    assert proof["metrics"]["wer"] == 0 and proof["metrics"]["onset_pitch_f1_100ms"] == 1
    assert draft.read_bytes() == original
    assert proof["chart_sha256"] == hashlib.sha256(verified.read_bytes()).hexdigest()


def test_verify_reused_library_copy_and_staged_audio_before_import(package, tmp_path, monkeypatch):
    from karaoke import songs

    library = tmp_path / "library"
    audio = Path(songs.validate(package)["audio"])
    expected = dict(
        expected_audio_sha256=hashlib.sha256(audio.read_bytes()).hexdigest(),
        expected_chart_sha256=hashlib.sha256(package.read_bytes()).hexdigest(),
    )
    first = songs.import_package(package, library, **expected)
    installed = Path(first["chart"])
    old = installed.read_text(encoding="utf-8")
    installed.write_text(old.replace(": 8 8 21", ": 8 8 23"), encoding="utf-8")
    assert installed.read_text(encoding="utf-8") != old
    with pytest.raises(SongError, match="mapa verificado"):
        songs.import_package(package, library, **expected)
    assert songs.validate(installed)

    # A valid WAV can also change between the identification pass and the actual copy.
    copy = songs.shutil.copy2

    def changed_copy(src, dest):
        copy(src, dest)
        if src == audio:
            with dest.open("r+b") as stream:
                stream.seek(-2, 2)
                stream.write(b"\xaa\xbb")

    monkeypatch.setattr(songs.shutil, "copy2", changed_copy)
    empty = tmp_path / "empty"
    with pytest.raises(SongError, match="grabación verificada"):
        songs.import_package(package, empty, **expected)
    assert list(empty.iterdir()) == []
