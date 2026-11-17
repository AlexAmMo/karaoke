import sqlite3

from karaoke import catalog, community_catalog as community


ES_HTML = """<html>
<a href="https://ultrastar-es.org/en/canciones/descargar/txt/retired42"
   title="Álex Ubago - Sigo Aquí">TXT</a>
<a href="https://ultrastar-es.org/en/canciones/descargar/txt/retired51"
   title="Álex Ubago - Sigo Aquí (Directo)">TXT</a>
<a href="https://ultrastar-es.org/en/canciones/descargar/txt/retired42"
   title="Álex Ubago - Sigo Aquí">TXT</a>
<a href="https://ultrastar-es.org.fake.example/en/canciones/descargar/txt/13"
   title="Álex Ubago - False source">Fake</a>
</html>
""".encode()

EU_XML = b"""
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="urn:image">
<url><loc>https://usdb.eu/Adele/SomeoneLikeYou</loc>
<image:image><image:caption>Adele - Someone Like You</image:caption></image:image></url>
<url><loc>https://usdb.eu/Adele/SomeoneLikeYou/460</loc>
<image:image><image:caption>Adele - Wrong redirect</image:caption></image:image></url>
<url><loc>https://fake.example/Adele/SomeoneLikeYou</loc>
<image:image><image:caption>Adele - False source</image:caption></image:image></url>
</urlset>"""


def test_index_discovery_keeps_editions_and_never_opens_historical_downloads(tmp_path, monkeypatch):
    calls = []

    def fetch(provider):
        calls.append(provider)
        return community._parse(provider, ES_HTML if provider == "es" else EU_XML)

    monkeypatch.setattr(community, "_fetch", fetch)
    results = community.search("sigo aqui alex ubago", tmp_path)
    assert {row["title"] for row in results} == {"Sigo Aquí", "Sigo Aquí (Directo)"}
    assert "espana:sigo-aqui" in {row["source"] for row in results}
    assert len({row["source"] for row in results}) == 2
    assert all("retired" not in row["catalogue_url"] for row in results)
    assert all(
        row["catalogue_url"].startswith("https://ultrastar-es.org/es/canciones?") for row in results
    )
    assert not community.search("False source", tmp_path)
    (eu_result,) = community.search("Adele", tmp_path)
    assert eu_result["catalogue_url"] == "https://usdb.eu/Adele/SomeoneLikeYou"
    assert calls == ["es", "eu"]


def test_stale_index_and_working_provider_survive_an_outage(tmp_path, monkeypatch):
    calls = []

    def fetch(provider):
        calls.append(provider)
        if provider == "es" and calls.count("es") == 2:
            raise OSError("sin conexión")
        return community._parse(provider, ES_HTML if provider == "es" else EU_XML)

    monkeypatch.setattr(community, "_fetch", fetch)
    original = community.search("Sigo Aquí", tmp_path)
    with sqlite3.connect(tmp_path / "community-v1.sqlite3") as db:
        db.execute("UPDATE feeds SET refreshed=0,attempted=0")
    assert original and community.search("Sigo Aquí", tmp_path) == original
    assert community.search("Adele", tmp_path)
    assert calls == ["es", "eu", "es", "eu"]


def test_alex_ubago_has_offline_assisted_fallback():
    (exact,) = catalog.assisted_songs("Sigo Aqui Alex Ubago")
    assert (exact["artist"], exact["title"]) == ("Álex Ubago", "Sigo Aquí")
    assert "cancion=" in catalog.assisted_entry_url(exact["source"])
