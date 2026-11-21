import hashlib
from pathlib import Path

import requests


def test_qt_source_retries_mirrors_and_verifies_each_archive(monkeypatch, tmp_path):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    import collect_sources

    content = b"upstream source archive"
    expected = hashlib.sha256(content).hexdigest()
    item = {
        "group": "qt",
        "filename": "module.tar.xz",
        "sha256": expected,
        "url": "https://download.qt.io/example.tar.xz",
    }
    seen = []

    class Response:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, _):
            yield self.data

    def get(url, **kwargs):
        seen.append(url)
        if len(seen) == 1:
            raise requests.ReadTimeout("temporary outage")
        return Response(b"damaged" if len(seen) == 2 else content)

    monkeypatch.setattr(collect_sources, "OUT", tmp_path)
    monkeypatch.setattr(collect_sources.requests, "get", get)
    monkeypatch.setattr(collect_sources.time, "sleep", lambda _: None)
    result = collect_sources.source_download(item)
    assert result["upstream_hash_checked"] and result["sha256"] == expected
    assert seen == collect_sources.source_urls(item["url"])
    assert (tmp_path / "qt/module.tar.xz").read_bytes() == content
    result = collect_sources.source_download(item)
    assert result["status"] == "collected" and len(seen) == 3
