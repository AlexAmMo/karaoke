"""Exercise the network boundary over real sockets, with independent browser sessions."""
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import pytest
import requests
from PIL import Image

from karaoke.remote_server import RemoteError, RemoteServer


@pytest.fixture
def room(tmp_path):
    calls = []

    def dispatch(client, name, operation, payload):
        calls.append((client, name, operation))
        if operation == "cover":
            return tmp_path / "cover.png"
        if operation == "action" and payload.get("stale"):
            raise RemoteError("Cola actualizada", 409)
        return {"name": name, "operation": operation}

    Image.new("RGB", (1, 1)).save(tmp_path / "cover.png")
    server = RemoteServer(dispatch, tmp_path / "room")
    server.start("127.0.0.1")
    try:
        yield server, calls
    finally:
        server.stop()


def browser():
    client = requests.Session()
    client.trust_env = False
    return client


def test_pair_consumers_concurrently_and_revoke_the_whole_room(room):
    server, calls = room
    base = server.url
    qr = server.qr_path
    secret = urlsplit(server.invite_url).fragment.removeprefix("join=")
    with Image.open(qr) as image:
        assert image.format == "PNG" and image.width == image.height and image.width >= 100

    def join(number):
        client = browser()
        credential = {"code": server.code} if number % 2 else {"secret": secret}
        name = f"Voz {number}"
        response = client.post(base + "/api/join", json={**credential, "name": name})
        assert response.json() == {"name": name}
        assert "HttpOnly" in response.headers["Set-Cookie"] and "SameSite=Strict" in response.headers["Set-Cookie"]
        assert client.get(base + "/api/me").json()["name"] == name
        assert client.post(base + "/api/search", json={"q": name}).json()["name"] == name
        return client

    with ThreadPoolExecutor(max_workers=6) as pool:
        clients = list(pool.map(join, range(6)))
    assert len({guest for guest, _, _ in calls}) == server.connected_count == 6
    client = clients[0]
    assert client.get(base + "/api/cover/example").headers["Content-Type"] == "image/png"
    assert client.post(base + "/api/action", json={"stale": True}).status_code == 409

    server.stop()
    assert not qr.exists()
    url = server.start("127.0.0.1")
    assert server.connected_count == 0 and server.qr_path != qr
    assert client.get(url + "/api/me").status_code == 401
    assert client.post(url + "/api/join", json={"secret": secret, "name": "Ana"}).status_code == 403


def test_mobile_site_and_request_boundaries(room):
    server, calls = room
    client = browser()
    base = server.url
    for asset in ("/", "/app.js", "/style.css"):
        response = client.get(base + asset)
        assert response.status_code == 200 and response.content
    assert client.get(base + "/api/cover/example").status_code == 401
    assert client.post(base + "/api/action", json={}).status_code == 401
    join = base + "/api/join"
    credentials = {"name": "Ana", "code": server.code}
    assert client.post(join, json=credentials, headers={"Origin": "https://example.org"}).status_code == 403
    assert client.post(join, json=credentials, headers={"Host": "example.org"}).status_code == 403
    assert client.post(join, json=["x"]).status_code == 400
    assert client.post(join, json={"name": "x" * 8192}).status_code == 413
    assert client.post(join, data=credentials).status_code == 415
    for _ in range(6):
        assert client.post(join, json={"name": "Ana", "code": "invalid"}).status_code == 403
    assert client.post(join, json=credentials).status_code == 429
    assert not calls
