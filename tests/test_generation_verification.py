import hashlib

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
        evidence = dict(chart_sha256=chart_hash, audio_sha256=audio_hash, video_id="0123456789a")
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
        finish(evidence)
        row = host.lab.row(uid)
        saved = host.store.queue()[0]
        assert row["state"] == "approved"
        assert (
            saved["song_id"] == row["song_id"] and saved["id"] == turn and "Luna" in saved["names"]
        )
        from pathlib import Path

        info = Path(host.song(row["song_id"])["chart"]).with_name("generation.json")
        proof = json.loads(info.read_text())
        assert proof["automatically_verified"] and proof["state"] == "verified"
        assert host.lab.approve(uid) == row["song_id"]
    finally:
        host.close()
