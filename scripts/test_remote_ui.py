#!/usr/bin/env python3
"""Mobile UI regressions with an in-memory host and no native app or microphone.

    uv run --locked --with playwright python scripts/test_remote_ui.py --channel chrome

The companion test_remote_browser.py exercises the real host/session contract.
"""

import argparse
import asyncio
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect


ROOT = Path(__file__).resolve().parents[1]


def control(page, name):
    return page.get_by_role("button", name=name, exact=True)


class Host:
    def __init__(self, web_root):
        self.web_root = web_root
        self.actions = []
        self.item = {
            "id": "turn-1", "title": "Canción de prueba", "artist": "Artista",
            "names": ["Ana"], "status": "working", "message": "",
            "voices": [{"name": "Ana", "singer": "ana", "input": None}],
        }
        self.state = {
            "revision": "r1", "queue": [self.item], "preparations": [],
            "library_revision": {"count": 0, "updated": 0}, "name": "Ana",
            "singers": [{"id": "ana", "name": "Ana"}, {"id": "bea", "name": "Bea"}],
            "inputs": [], "active": None, "paused": False, "music": 0,
            "pitch_precision": 1, "previewing": False,
        }

    async def route(self, route):
        path = urlparse(route.request.url).path
        status = 200
        if path == "/api/me":
            result = {"name": "Ana"}
        elif path == "/api/state":
            result = self.state
        elif path == "/api/search":
            result = {"items": [], "page": 0, "more": False, "busy": False}
        elif path == "/api/action":
            payload = route.request.post_data_json
            self.actions.append(payload)
            if payload["op"] in {"rename", "start", "up", "down", "remove", "retry"} and payload.get("revision") != self.state["revision"]:
                status, result = 409, {"error": "La cola ha cambiado. Revisa el orden actualizado."}
            else:
                result = {"ok": True}
        elif path == "/api/mic-stop":
            result = {"ok": True}
        elif path.startswith("/api/"):
            raise AssertionError(f"Unexpected API request: {path}")
        else:
            file = self.web_root / ("index.html" if path == "/" else path.lstrip("/"))
            if not file.is_file():
                await route.fulfill(status=404)
            else:
                await route.fulfill(body=file.read_bytes(), content_type=mimetypes.guess_type(file)[0] or "application/octet-stream")
            return
        await route.fulfill(status=status, json=result)

    async def refresh(self, page):
        # Use the same foreground/reconnection refresh entry point as a phone.
        async with page.expect_response(lambda response: response.url.endswith("/api/state")):
            await page.evaluate("window.dispatchEvent(new Event('online'))")
        await page.wait_for_function("revision => state.revision === revision", arg=self.state["revision"])


async def live_turn(page, host, output, width):
    await page.locator('[data-tab="queue"]').click()
    await control(page, "Opciones del turno 1, Canción de prueba").click()
    sheet = page.locator("#sheet")
    await expect(sheet).to_contain_text("Artista · Preparando")
    await page.get_by_text("Asignar perfiles y micrófonos", exact=True).click()
    await control(page, "Añadir voz").click()
    await page.get_by_label("Perfil del cantante").last.select_option("bea")
    await page.get_by_label("Cantante", exact=True).fill("Ana editando")
    before = await page.evaluate("""() => {
        const field = document.getElementById('singer-0');
        window.originalSingerField = field;
        field.focus(); field.setSelectionRange(2, 6);
        const sheet = document.getElementById('sheet');
        sheet.scrollTop = 65;
        return {scroll:sheet.scrollTop, focused:document.activeElement === field};
    }""")
    assert before["focused"] and before["scroll"] > 0, before
    host.state["revision"] = "r2"
    host.item["status"] = "ready"
    await host.refresh(page)
    await expect(sheet).to_contain_text("Artista · Lista")
    await expect(sheet.get_by_role("button", name="Empezar a cantar", exact=True)).to_be_visible()
    preserved = await page.evaluate("""() => {
        const field = document.getElementById('singer-0');
        return {sameNode:field === window.originalSingerField,
          focused:document.activeElement === field, value:field.value,
          selection:[field.selectionStart, field.selectionEnd],
          scroll:document.getElementById('sheet').scrollTop,
          profiles:[...document.querySelectorAll('[aria-label="Perfil del cantante"]')].map(el => el.value),
          overflow:document.documentElement.scrollWidth > innerWidth};
    }""")
    assert preserved == {"sameNode": True, "focused": True, "value": "Ana editando",
                         "selection": [2, 6], "scroll": before["scroll"],
                         "profiles": ["ana", "bea"], "overflow": False}, preserved
    await sheet.screenshot(path=str(output / f"live-turn-edits-{width}.png"))
    await control(page, "Guardar cantantes").click()
    await expect(sheet).not_to_be_visible()
    assert host.actions[-1]["revision"] == "r2", host.actions[-1]
    assert host.actions[-1]["names"] == ["Ana editando"]

    # An unrelated state refresh must not silently overwrite another singer edit.
    await control(page, "Opciones del turno 1, Canción de prueba").click()
    await page.get_by_label("Cantante", exact=True).fill("Mi cambio local")
    host.state["revision"] = "r3"
    host.item["names"] = ["Otro mando"]
    await host.refresh(page)
    await control(page, "Guardar cantantes").click()
    await expect(page.locator("#feedback")).to_contain_text("La cola ha cambiado")
    assert host.actions[-1]["revision"] == "r2", host.actions[-1]

    # Reuse the open sheet for all ordinary host status transitions.
    await control(page, "Opciones del turno 1, Canción de prueba").click()
    host.state["revision"] = "r4"
    host.item["status"] = "error"
    host.item["message"] = "Preparación fallida. Puedes reintentar."
    await host.refresh(page)
    await expect(sheet.get_by_role("button", name="Reintentar", exact=True)).to_be_visible()
    await expect(sheet.get_by_role("button", name="Empezar a cantar", exact=True)).not_to_be_visible()
    await expect(sheet).to_contain_text(host.item["message"])
    host.state["revision"] = "r5"
    host.item.update(status="starting", message="")
    host.state["active"] = host.item["id"]
    await host.refresh(page)
    await expect(sheet.get_by_role("button", name="Pausar", exact=True)).to_be_disabled()
    host.state["revision"] = "r6"
    host.item["status"] = "singing"
    await host.refresh(page)
    await expect(sheet.get_by_role("button", name="Pausar", exact=True)).to_be_enabled()
    host.state["paused"] = True
    await host.refresh(page)
    await expect(sheet.get_by_role("button", name="Reanudar", exact=True)).to_be_visible()
    host.state["revision"] = "r7"
    host.state["queue"] = []
    host.state["active"] = None
    await host.refresh(page)
    await expect(sheet).to_contain_text("Este turno ya ha terminado.")
    await expect(sheet.get_by_role("button", name="Terminar canción", exact=True)).not_to_be_visible()
    await control(page, "Cerrar").click()
    await control(page, "Ajustes de la sesión").click()
    await host.refresh(page)
    await expect(page.locator("#sheet-title")).to_have_text("Ajustes de la sesión")
    await control(page, "Cerrar").click()
    return preserved


async def microphone_reopen(page, output, width):
    # No media is opened: simulate the existing voice module's completion signal.
    await page.evaluate("""() => {
        Object.defineProperty(window, 'isSecureContext', {value:true});
        Object.defineProperty(navigator, 'mediaDevices', {value:{}});
        KaraokeVoice.start = async (_signal, ended) => {window.simulateMicEnded = ended;};
        KaraokeVoice.stop = () => {};
    }""")
    await control(page, "Ajustes de la sesión").click()
    await control(page, "Usar este móvil como micrófono").click()
    await expect(page.locator("#sheet")).to_contain_text("Entrada asignada a tu cantante.")
    await control(page, "Cerrar").click()
    await control(page, "Ajustes de la sesión").click()
    await expect(control(page, "Desactivar mi micrófono")).to_be_visible()
    await page.evaluate("window.simulateMicEnded()")
    await expect(page.locator("#sheet")).to_contain_text("Micrófono apagado.")
    await expect(control(page, "Usar este móvil como micrófono")).to_be_visible()
    await expect(control(page, "Desactivar mi micrófono")).to_have_count(0)
    await page.locator('#sheet [role="status"]').scroll_into_view_if_needed()
    await page.screenshot(path=str(output / f"microphone-ended-{width}.png"))
    await control(page, "Cerrar").click()


async def generation_states(page, host, output, width):
    await expect(page.locator("#feedback")).to_have_text("")
    host.state["queue"] = [host.item]
    host.item["names"] = ["Ana"]
    for status, message, caption in [
        ("waiting", "Pendiente de generar mapa y letra.", "En espera"),
        ("working", "Preparando la letra y las notas.", "Preparando"),
        ("review", "Revisa el mapa y la letra en el ordenador.", "Pendiente de revisión"),
        ("host", "La generación se ha detenido. Reintenta en el ordenador.", "Pendiente en el ordenador"),
    ]:
        host.item.update(status=status, message=message)
        host.state["revision"] = "generation-" + status
        await host.refresh(page)
        row = page.locator("#list li")
        await expect(row).to_contain_text(caption)
        await expect(row).to_contain_text(message)
        await expect(row).to_contain_text("Ana")
        assert not await page.evaluate("document.documentElement.scrollWidth > innerWidth")
        if status == "review":
            await page.screenshot(path=str(output / f"generation-review-{width}.png"))
        await control(page, "Opciones del turno 1, Canción de prueba").click()
        await expect(page.locator("#sheet")).to_contain_text(message)
        await expect(page.locator("#sheet").get_by_role("button", name="Reintentar", exact=True)).not_to_be_visible()
        await expect(page.locator("#sheet").get_by_role("button", name="Empezar a cantar", exact=True)).not_to_be_visible()
        await control(page, "Cerrar").click()
    host.item.update(status="ready", message="")
    host.state["revision"] = "generation-approved"
    await host.refresh(page)
    await control(page, "Opciones del turno 1, Canción de prueba").click()
    await expect(page.locator("#sheet").get_by_role("button", name="Empezar a cantar", exact=True)).to_be_visible()
    await control(page, "Cerrar").click()


async def main(args):
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, channel=args.channel)
        try:
            for width in (390, 320):
                context = await browser.new_context(viewport={"width": width, "height": 700}, is_mobile=True, has_touch=True)
                host = Host(args.web_root)
                await context.route("http://karaoke.test/**", host.route)
                page = await context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.goto("http://karaoke.test/")
                await expect(page.locator("#controller")).to_be_visible()
                preserved = await live_turn(page, host, args.output, width)
                await microphone_reopen(page, args.output, width)
                await generation_states(page, host, args.output, width)
                assert not errors, errors
                results.append({"width": width, "turn": preserved, "microphone_reopen": "passed", "generation_states": "passed"})
                print(f"PASS mobile UI {width}px: live state, edits, conflicts, microphone reopen, generation states", flush=True)
                await context.close()
        finally:
            await browser.close()
    (args.output / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default="chrome")
    parser.add_argument("--web-root", type=Path, default=ROOT / "src/karaoke/remote_web")
    parser.add_argument("--output", type=Path, default=ROOT / "build/mobile-review/verified")
    asyncio.run(main(parser.parse_args()))
