import json
import pytest
from karaoke.store import Store
from karaoke.songs import import_package


def test_repeated_requests_share_one_preparation_but_have_separate_turns(tmp_path, package):
    store = Store(tmp_path / "state.sqlite")
    a = store.request("usdb:1", {"kind": "usdb"}, ["Ana"])
    b = store.request("usdb:1", {"kind": "usdb"}, ["José", "Ana"])
    assert a != b
    assert len(store.rows("SELECT * FROM jobs")) == 1
    info = import_package(package, tmp_path / "library")
    store.save_song(info, "usdb:1")
    assert [t["song_id"] for t in store.queue()] == [info["id"], info["id"]]
    assert json.loads(store.queue()[1]["names"]) == ["José", "Ana"]
    store.close()


def test_same_package_from_two_sources_is_reused(tmp_path, package):
    store = Store(tmp_path / "state.sqlite")
    info = import_package(package, tmp_path / "library")
    store.save_song(info, "import:folder-one")
    store.save_song(info, "import:folder-two")
    store.request("import:folder-two", {}, ["Ana"])
    assert store.queue()[0]["song_id"] == info["id"]
    assert store.rows("SELECT * FROM jobs") == []
    store.close()


def test_crash_recovery_preserves_pending_order_without_autoplay(tmp_path):
    path = tmp_path / "state.sqlite"
    store = Store(path)
    first = store.request("usdb:1", {}, ["Ana"])
    second = store.request("usdb:2", {}, ["José"])
    store.execute("UPDATE turns SET state='singing' WHERE id=?", (first,))
    store.execute("UPDATE jobs SET state='working' WHERE source='usdb:1'")
    store.close()
    reopened = Store(path)
    assert [(r["id"], r["state"]) for r in reopened.queue()] == [
        (first, "queued"),
        (second, "queued"),
    ]
    assert {r["state"] for r in reopened.rows("SELECT state FROM jobs")} == {"waiting"}
    reopened.close()


def test_skip_and_reorder_leave_other_turns_in_order(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    turns = [store.request("usdb:" + str(i), {}, ["Ana"]) for i in range(4)]
    store.execute("UPDATE turns SET state='finished' WHERE id=?", (turns[2],))
    assert [r["id"] for r in store.queue()] == [turns[0], turns[1], turns[3]]
    store.reorder(turns[3], -1)
    assert [r["id"] for r in store.queue()] == [turns[0], turns[3], turns[1]]
    store.close()


@pytest.mark.parametrize("names", [[], [""], [str(i) for i in range(11)]])
def test_invalid_players_roll_back_the_whole_request(tmp_path, names):
    store = Store(tmp_path / "state.sqlite")
    with pytest.raises(ValueError):
        store.request("usdb:1", {}, names)
    assert store.rows("SELECT * FROM jobs") == []
    assert store.queue() == []
    store.close()


def test_updated_source_reassigns_alias_without_deleting_old_package(tmp_path, package):
    store = Store(tmp_path / "state.sqlite")
    first = import_package(package, tmp_path / "library")
    store.save_song(first, "import:folder")
    package.write_text(
        package.read_text(encoding="utf-8").replace("Canción de prueba", "Otra edición"),
        encoding="utf-8",
        newline="\n",
    )
    second = import_package(package, tmp_path / "library")
    store.save_song(second, "import:folder")
    store.close()
    store = Store(tmp_path / "state.sqlite")
    store.request("import:folder", {}, ["Ana"])
    assert store.queue()[0]["song_id"] == second["id"]
    assert len(store.rows("SELECT * FROM songs")) == 2
    store.close()
