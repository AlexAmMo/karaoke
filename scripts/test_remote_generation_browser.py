#!/usr/bin/env python3
"""Test generation states through real HTTP, RemoteSession and a temporary Service.

    uv run --locked --with playwright python scripts/test_remote_generation_browser.py

Only catalogue metadata, worker outcomes and a silent generated package are
fixtures. No browser request is intercepted; no inference or native engine runs.
"""

import argparse
import asyncio
from contextlib import suppress
import json
from pathlib import Path
import tempfile
import time
from urllib.parse import urlparse
import wave

from playwright.async_api import async_playwright, expect

from karaoke.service import Service


ROOT = Path(__file__).resolve().parents[1]
TITLE = "Generación de prueba"


def button(page, name):
    return page.get_by_role("button", name=name, exact=True)


def queue_row(page):
    return page.locator("#list li").filter(has=page.get_by_text(TITLE, exact=True))


def failed_turn(host):
    """Use the ordinary result action, then deliver a downloader failure fixture."""
    source = "allkaraoke:generation-browser-fixture"
    host.fields["player1"] = "Ana"
    host.results = [{"source": source, "title": TITLE, "artist": "Fixture",
                     "language": "Spanish", "video_id": "IA0uSub1xy4"}]
    host.handle({"action": f"result:queue:{host.search_generation}:{source}"})
    turn, = host.store.queue()
    job, = host.store.rows("SELECT * FROM jobs WHERE source=?", (source,))
    host.store.execute("UPDATE jobs SET state='working' WHERE id=?", (job["id"],))
    host.store.preparation_failed(job["id"], "Fallo de descarga simulado para esta prueba.")
    assert host.store.queue()[0]["preparation"] == "error"
    return turn["id"]


def generated_package(directory):
    directory.mkdir(parents=True)
    with wave.open(str(directory / "audio.wav"), "wb") as audio:
        audio.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 48000 * 4)
    (directory / "song.txt").write_text(
        f"#TITLE:{TITLE}\n#ARTIST:Fixture\n#LANGUAGE:Spanish\n#BPM:120\n"
        "#GAP:0\n#MP3:audio.wav\n: 0 8 21 sí\n- 8\n: 8 8 21 no\nE\n",
        encoding="utf-8",
    )


async def pulse(host):
    while True:
        host.remote.tick()  # Deliberately never start download or generation workers.
        await asyncio.sleep(0.02)


async def join(browser, host, width, name, http, errors):
    context = await browser.new_context(viewport={"width": width, "height": 700}, is_mobile=True, has_touch=True)
    page = await context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))

    def response_seen(response):
        path = urlparse(response.url).path
        if path.startswith("/api/"):
            payload = response.request.post_data_json if response.request.method == "POST" else {}
            http.append({"phone": name, "path": path, "op": (payload or {}).get("op"), "status": response.status})

    page.on("response", response_seen)
    await page.goto(host.remote.server.url)
    await page.get_by_label("Tu nombre").fill(name)
    await page.get_by_label("Código del ordenador").fill(host.remote.server.code)
    await button(page, "Entrar en Karaoke").click()
    await expect(page.locator("#controller")).to_be_visible()
    await page.locator('[data-tab="queue"]').click()
    await expect(queue_row(page)).to_contain_text("Necesita atención")
    return context, page


async def open_turn(page):
    await queue_row(page).get_by_role("button", name=f"Opciones del turno 1, {TITLE}", exact=True).click()


async def action_response(page, control, expected):
    async with page.expect_response(lambda response: urlparse(response.url).path == "/api/action") as response:
        await control.click()
    received = await response.value
    assert received.status == expected, (received.status, await received.text())


async def stale_action(page, turn, op):
    result = await page.evaluate("""async ({id, op}) => {
        const stateResponse = await fetch('/api/state', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
        const current = await stateResponse.json();
        const response = await fetch('/api/action', {method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({op, id, revision:current.revision, request_id:crypto.randomUUID()})});
        return {status:response.status, body:await response.json()};
    }""", {"id": turn, "op": op})
    assert result["status"] == 409, result
    return result


async def scenario(host, browser, output):
    http, errors = [], []
    turn = failed_turn(host)
    a_context, ana = await join(browser, host, 390, "Ana", http, errors)
    b_context, bea = await join(browser, host, 320, "Bea", http, errors)
    try:
        await open_turn(ana)
        await ana.get_by_label("Cantante", exact=True).fill("Ana preparando")
        await ana.evaluate("""() => {
            window.editedField = document.getElementById('singer-0');
            editedField.focus(); editedField.setSelectionRange(2, 6);
        }""")
        host.handle({"action": "lab:from-turn:" + turn})
        host.handle({"action": "lab:enqueue"})
        draft = host.draft_id
        for stage, message, visible in [
            ("working", "Transcribiendo la letra", "Transcribiendo la letra"),
            ("review", "Listo para revisar", "Revisa la letra y las notas en el ordenador antes de cantar."),
        ]:
            host.store.execute("UPDATE drafts SET state=?,message=? WHERE id=?", (stage, message, draft))
            await expect(ana.locator("#sheet")).to_contain_text(visible)
            await expect(queue_row(bea)).to_contain_text(visible)
            await expect(ana.locator("#sheet").get_by_role("button", name="Empezar a cantar", exact=True)).not_to_be_visible()
            await expect(ana.locator("#sheet").get_by_role("button", name="Reintentar", exact=True)).not_to_be_visible()
            assert await ana.evaluate("""() => document.getElementById('singer-0') === editedField
              && document.activeElement === editedField && editedField.value === 'Ana preparando'
              && editedField.selectionStart === 2 && editedField.selectionEnd === 6""")
        await ana.screenshot(path=str(output / "review-open-390.png"))
        await bea.screenshot(path=str(output / "review-queue-320.png"))
        rejected = [await stale_action(bea, turn, op) for op in ("retry", "start")]

        generated_package(host.lab.root / draft / "draft")
        host.lab.approve(draft)
        await expect(ana.locator("#sheet")).to_contain_text("Fixture · Lista")
        await expect(ana.locator("#sheet").get_by_role("button", name="Empezar a cantar", exact=True)).to_be_visible()
        assert await ana.evaluate("""() => document.getElementById('singer-0') === editedField
          && document.activeElement === editedField && editedField.value === 'Ana preparando'
          && editedField.selectionStart === 2 && editedField.selectionEnd === 6""")
        await ana.screenshot(path=str(output / "ready-open-390.png"))
        await action_response(ana, button(ana, "Guardar cantantes"), 200)
        for page in (ana, bea):
            await expect(queue_row(page)).to_contain_text("Ana preparando")
        print("PASS real HTTP: failed turn → generation → review → approval, same input and saved edits", flush=True)

        await open_turn(ana)
        await ana.get_by_label("Cantante", exact=True).fill("Edición sin guardar")
        await open_turn(bea)
        await bea.get_by_label("Cantante", exact=True).fill("Cambio desde Bea")
        await action_response(bea, button(bea, "Guardar cantantes"), 200)
        await expect(queue_row(ana)).to_contain_text("Cambio desde Bea")
        await expect(ana.get_by_label("Cantante", exact=True)).to_have_value("Edición sin guardar")
        await action_response(ana, button(ana, "Guardar cantantes"), 409)
        await expect(ana.locator("#feedback")).to_contain_text("La cola ha cambiado")
        current, = host.store.queue()
        assert current["id"] == turn and json.loads(current["names"]) == ["Cambio desde Bea"]
        assert current["song_id"] and not errors, errors
        for page in (ana, bea):
            assert not await page.evaluate("document.documentElement.scrollWidth > innerWidth")
        print("PASS real HTTP: stale retry/start rejected, competing singer edit preserved", flush=True)
        return {"http": http, "javascript_errors": errors, "rejected_before_approval": rejected,
                "turn_identity_preserved": True, "concurrent_edit_preserved": True,
                "browser": browser.version, "viewports": [390, 320],
                "scope": "Real Service/SQLite/RemoteSession/HTTP; synthetic worker phases and silent package; no engine or inference"}
    finally:
        await a_context.close()
        await b_context.close()


async def main(args):
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="karaoke-generation-browser-") as directory:
        host = Service(Path(directory))
        host.artwork.close()  # This test never fetches external artwork.
        host.remote.start("127.0.0.1")
        tick = asyncio.create_task(pulse(host))
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True, channel=args.channel, args=["--no-proxy-server"])
                try:
                    result = await scenario(host, browser, args.output)
                finally:
                    await browser.close()
        finally:
            tick.cancel()
            with suppress(asyncio.CancelledError):
                await tick
            host.close()
    result["elapsed_seconds"] = round(time.monotonic() - started, 2)
    (args.output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default="chrome")
    parser.add_argument("--output", type=Path, default=ROOT / "build/ux-next/remote-generation-real")
    asyncio.run(main(parser.parse_args()))
