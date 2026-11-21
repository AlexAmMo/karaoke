import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from karaoke.participants import Participants, VoiceNames
from karaoke.store import Store
from karaoke.songs import SongError


def test_shared_mics_and_atomic_reservations(tmp_path):
    store = Store(tmp_path / "room.db")
    people = Participants(store)
    inputs = {"left": {"device": 0, "channel": 0}, "right": {"device": 0, "channel": 1}}
    identities = [people.create("Voz" if i < 2 else f"Voz {i}") for i in range(10)]
    for i, uid in enumerate(identities):
        people.configure(uid, input_key="left" if i < 5 else "right")
    with pytest.raises(SongError):
        people.create("Once")

    def turn(i, j):
        return store.request(
            "song",
            {},
            VoiceNames(
                [{"singer": identities[i]}, {"singer": identities[j]}],
                {p["id"]: p for p in people.list()},
            ),
        )

    with pytest.raises(SongError):
        turn(0, 1)
    assert not store.queue() and not store.rows("SELECT * FROM jobs")
    first, second = turn(0, 5), turn(1, 6)

    def start(t):
        row = store.rows("SELECT * FROM turns WHERE id=?", (t,))[0]
        try:
            return people.reserve(row, inputs, 10)
        except SongError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(x is not None for x in pool.map(start, [first, second])) == 1
    active = store.rows("SELECT DISTINCT turn_id FROM reservations")[0]["turn_id"]
    assert len(store.rows("SELECT * FROM reservations")) == 2
    store.execute("UPDATE turns SET state='finished' WHERE id=?", (active,))
    other = second if active == first else first
    assert len(start(other)) == 2
    store.close()
    restored = Store(tmp_path / "room.db")
    assert not restored.rows("SELECT * FROM reservations")
    assert len(Participants(restored).list()) == 10
    assert restored.queue()[0]["state"] == "queued"
    restored.close()


def test_migrate_legacy_and_performance_identity(tmp_path):
    path = tmp_path / "db.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    db.execute("PRAGMA user_version=2")
    db.execute("INSERT INTO settings VALUES(?,?)", ("music", "25"))
    db.commit()
    db.close()
    store = Store(path)
    people = Participants(store)
    assert (
        sqlite3.connect(path.with_name(path.name + ".before-v3"))
        .execute("PRAGMA user_version")
        .fetchone()[0]
        == 2
    )
    assert store.setting("music") == 25
    a = people.create("Ana", "phone-one")
    b = people.create("Ana", "phone-two")
    assert a != b and people.create("Ana", "phone-one") == a
    turn = store.request("demo", {}, ["Voz antigua"])
    people.set_voices(turn, [{"singer": a, "input": "usb1"}, {"singer": b, "input": "usb2"}])
    row = store.queue()[0]
    with pytest.raises(SongError):
        people.reserve(row, {"usb1": {}}, 10)
    assert store.queue()[0]["state"] == "queued"
    assert json.loads(row["names"]) == ["Ana", "Ana"]
    with pytest.raises(SongError):
        people.retire(a)
    store.close()


def test_two_unassigned_singers_cannot_fall_back_to_the_same_usb(tmp_path):
    store = Store(tmp_path / "room.db")
    try:
        people = Participants(store)
        store.request("track", {}, ["Luna", "Sol"])
        turn = store.queue()[0]
        with pytest.raises(SongError, match="entrada independiente"):
            people.reserve(turn, {"usb-left": {"assigned": 1}}, 10)
        assert store.queue()[0]["state"] == "queued" and not store.rows(
            "SELECT * FROM reservations"
        )
    finally:
        store.close()


def test_native_start_rejection_is_tied_to_the_specific_attempt(tmp_path, package):
    from karaoke.service import Service
    from karaoke.songs import import_package

    host = Service(tmp_path / "host")
    try:
        track = import_package(package, host.library)
        host.store.save_song(track)
        turn = host.enqueue_song(track["id"])
        host.engine = {"state": "idle", "max_singers": 10, "synthetic": True}
        host.start(turn)
        engine = host.engine
        engine["start_failure"] = {"token": turn, "attempt": "previous", "message": "Old error"}
        (host.ipc / "engine.json").write_text(json.dumps(engine))
        host.tick()
        assert host.active == turn
        engine["start_failure"].update(attempt=host.start_attempt, message="Micro desconectado")
        (host.ipc / "engine.json").write_text(json.dumps(engine))
        host.tick()
        assert host.active is None and host.message == "Micro desconectado"
        assert host.store.queue()[0]["state"] == "queued" and not host.store.rows(
            "SELECT * FROM reservations"
        )
    finally:
        host.close()
