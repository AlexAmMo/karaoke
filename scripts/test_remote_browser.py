#!/usr/bin/env python3
"""Exercise mobile turn menus and room closure against an isolated desktop session.

With Chrome installed, from the repository root:
    uv run --locked --with playwright python scripts/test_remote_browser.py --channel chrome
Add --launcher PATH to exercise an installed package. Without --channel this uses
Playwright's Chromium (install it with uv run --with playwright playwright install chromium).
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import requests
from playwright.async_api import async_playwright, expect

from test_session import ROOT, Session, read_json


def button(page, name):
    return page.get_by_role("button", name=name, exact=True)


def row(page, title):
    return page.locator("#list li").filter(has=page.get_by_text(title, exact=True))


async def accepted_action(page, control, op):
    def matches(response):
        return (
            response.url.endswith("/api/action")
            and response.request.method == "POST"
            and response.request.post_data_json.get("op") == op
        )

    async with page.expect_response(matches, timeout=15000) as pending:
        await control.click()
    response = await pending.value
    result = await response.json()
    assert response.ok and result.get("ok"), (op, response.status, result)


async def expect_queue(page, songs):
    await expect(page.locator('[data-tab="queue"]')).to_have_attribute("aria-current", "page")
    await expect(page.locator("#list li")).to_have_count(len(songs), timeout=15000)
    for title, singer in songs:
        await expect(row(page, title)).to_contain_text(singer, timeout=15000)


async def report_phones(phones):
    for name, page in phones.items():
        try:
            snapshot = await page.evaluate("""() => ({
              tab: document.querySelector('[data-tab][aria-current="page"]')?.textContent,
              notice: document.querySelector('#connection').innerText,
              feedback: document.querySelector('#feedback').innerText,
              rows: Array.from(document.querySelectorAll('#list li'), el => el.innerText),
              dialog: document.querySelector('dialog[open]')?.innerText,
              closed: !document.querySelector('#closed-room').hidden,
              hidden: document.hidden,
              online: navigator.onLine,
            })""")
            print(f"{name} UI: {json.dumps(snapshot, ensure_ascii=True)}", flush=True)
        except Exception as error:
            print(f"{name} UI unavailable: {error}", flush=True)


def host_snapshot(session, phase, *, logs=False):
    view = read_json(session.ipc / "view.json")
    engine = read_json(session.ipc / "engine.json")
    process = session.process
    print(f"Host {phase}: " + json.dumps({
        "pid": process.pid if process else None,
        "exit": process.poll() if process else None,
        "view_page": view.get("page"),
        "engine_state": engine.get("state"),
        "engine_demo": engine.get("synthetic"),
    }, ensure_ascii=True), flush=True)
    if not logs:
        return
    for path in (session.data / f"launcher-{session.launch_count}.log",
                 session.data / "engine.log", session.data / "last-error.txt"):
        try:
            with path.open("rb") as stream:
                stream.seek(max(0, path.stat().st_size - 3500))
                tail = stream.read().decode("utf-8", "replace")
            tail = re.sub(r"(?i)#join=[^\s&]+|invite-[a-z0-9]+\.png|(?<![0-9])[0-9]{6}(?![0-9])", "[redacted]", tail)
            print(f"{path.name}: " + json.dumps(tail, ensure_ascii=True), flush=True)
        except OSError as error:
            print(f"{path.name}: {error.__class__.__name__}", flush=True)


def direct_lan_probe(url):
    with requests.Session() as probe:
        probe.trust_env = False
        response = probe.get(url, timeout=5)
        print("Direct LAN HTTP response:", response.status_code, flush=True)
        response.raise_for_status()


async def join(browser, profile, name, url, code):
    context = await browser.new_context(**profile)
    page = await context.new_page()
    await page.goto(url)
    await page.get_by_label("Tu nombre").fill(name)
    await page.get_by_label("Código del ordenador").fill(code)
    await button(page, "Entrar en Karaoke").click()
    await page.get_by_role("searchbox").wait_for()
    return page


async def late_add(page, observer, title, new_name, *, lose_first_response):
    """Change only delivery timing: every POST is processed by the real host."""
    await page.locator("[data-tab=search]").click()
    await page.get_by_role("searchbox").fill("")
    await page.get_by_label("Solo descargadas").check()
    added = asyncio.Event()
    release = asyncio.Event()

    async def delay(route):
        response = await route.fetch()
        assert response.ok
        added.set()
        await release.wait()
        await route.fulfill(response=response)

    async def lose(route):
        response = await route.fetch()
        assert response.ok
        await route.abort("failed")

    if lose_first_response:
        await page.route("**/api/action", lose, times=1)
        await button(page, "Añadir " + title).click()
        await row(observer, title).wait_for()
        await button(page, "Comprobar").wait_for()
    await page.route("**/api/action", delay, times=1)
    control = "Comprobar" if lose_first_response else "Añadir " + title
    try:
        await button(page, control).click()
        await asyncio.wait_for(added.wait(), 8)
        await page.locator("[data-tab=queue]").click()
        await row(page, title).get_by_role("button", name=re.compile("Opciones del turno")).click()
        dialog = page.get_by_role("dialog")
        await dialog.get_by_label("Cantante", exact=True).fill(new_name)
    finally:
        release.set()
    await expect(page.locator("#feedback")).to_contain_text("Turno añadido a la cola")
    await expect(dialog).to_be_visible()
    await expect(dialog.get_by_label("Cantante", exact=True)).to_have_value(new_name)
    await accepted_action(page, button(dialog, "Guardar cantantes"), "rename")
    await expect(dialog).to_be_hidden()
    for phone in (page, observer):
        await expect(row(phone, title)).to_have_count(1)
        await expect(row(phone, title)).to_contain_text(new_name)
    print(f"PASS: {'retry' if lose_first_response else 'add'} preserved the open menu and edits", flush=True)


async def test_phones(session, browser_type, channel, capture=None):
    view = session.ipc / "view.json"

    def open_room():
        session.event("page:Ajustes")
        session.event("remote:start")
        session.wait(lambda _: any(r["kind"] == "qr" for r in read_json(view).get("rows", [])))
        rows = read_json(view)["rows"]
        address = next(r for r in rows if r.get("label", "").startswith("http://"))
        code = re.search(r"\b\d{6}\b", address["sub"]).group()
        return address["label"], code

    url, code = open_room()
    host_snapshot(session, "room ready")
    direct_lan_probe(url)
    async with async_playwright() as playwright:
        # These phones join the local network directly, including on CI hosts
        # with a system-wide web proxy configured.
        options = {"args": ["--no-proxy-server"]} if browser_type == "chromium" else {}
        browser = await getattr(playwright, browser_type).launch(channel=channel, **options)
        phones = {}
        try:
            host_snapshot(session, "before browser joins")
            ana, luis, mar = await asyncio.gather(*(
                join(browser, playwright.devices[model], name, url, code)
                for model, name in (("iPhone 13", "Ana"), ("Pixel 7", "Luis"), ("iPhone SE", "Mar"))
            ))
            phones = {"Ana": ana, "Luis": luis, "Mar": mar}
            host_snapshot(session, "after browser joins")
            await mar.locator("[data-tab=queue]").click()
            if capture:
                capture.mkdir(exist_ok=True, parents=True)
                await ana.get_by_role("checkbox", name="Solo descargadas").check()
                await expect(row(ana, "Probe A")).to_be_visible()
                await expect(ana.locator("#list li")).to_have_count(2)
                await ana.evaluate("document.fonts.ready")
                assert await ana.evaluate("""document.fonts.check('16px "Instrument Sans"')""")
                for width, height in ((390,844),(320,568)):
                    await ana.set_viewport_size({'width':width, 'height':height})
                    assert await ana.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    await ana.screenshot(path=capture / f"{browser_type}-{width}.png")
                await ana.set_viewport_size({'width':390,'height':844})
            await late_add(ana, mar, "Probe A", "Ana y Mar", lose_first_response=False)
            await late_add(luis, mar, "Probe B", "Luis y Mar", lose_first_response=True)

            first = ("Probe A", "Ana y Mar")
            second = ("Probe B", "Luis y Mar")
            await asyncio.gather(*(expect_queue(phone, (first, second)) for phone in phones.values()))
            await mar.context.set_offline(True)
            await expect(mar.locator("#connection")).to_contain_text("Reconectando", timeout=15000)
            await row(luis, "Probe B").get_by_role("button", name=re.compile("Opciones del turno")).click()
            await button(luis, "Quitar de la cola").click()
            await accepted_action(luis, button(luis, "Quitar turno"), "remove")
            await expect(luis.get_by_role("dialog")).to_be_hidden()
            await asyncio.gather(*(expect_queue(phone, (first,)) for phone in (ana, luis)))
            await expect(button(mar, "Reintentar")).to_be_visible(timeout=25000)
            await expect(mar.locator("#connection")).to_contain_text("No se encuentra el ordenador")
            await mar.context.set_offline(False)
            await expect(mar.locator("#connection")).to_be_hidden(timeout=15000)
            await expect_queue(mar, (first,))
            print("PASS: transient wifi loss recovered and synchronized the queue", flush=True)

            await row(ana, "Probe A").get_by_role("button", name=re.compile("Opciones del turno")).click()
            await mar.context.set_offline(True)
            await expect(mar.locator("#connection")).to_contain_text("Reconectando", timeout=15000)
            session.event("remote:stop")
            for page in (ana, luis, mar):
                if page is mar:
                    # Rejoin wifi after the two connected phones have already seen the closure.
                    await mar.context.set_offline(False)
                await expect(page.get_by_role("heading", name="La sala se ha cerrado")).to_be_visible(timeout=12000)
                await expect(page.locator("#controller")).to_be_hidden()
                await expect(page.get_by_role("dialog")).to_be_hidden()
            requests_after_close = []
            for page in (ana, luis, mar):
                page.on("request", lambda request: requests_after_close.append(request.url))
            # Leave time for the slowest normal retry (2.5s); a terminal view must stop polling.
            await asyncio.sleep(3)
            assert not any(url.endswith("/api/state") for url in requests_after_close)
            print("PASS: closure reached the editing guest and the returning guest; polling stopped", flush=True)
        except Exception:
            await report_phones(phones)
            print("Host test turns:", session.rows("SELECT state, names FROM turns ORDER BY created"), flush=True)
            try:
                direct_lan_probe(url)
            except requests.RequestException as error:
                print("Direct LAN failure:", repr(error), flush=True)
            raise
        finally:
            await browser.close()


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", type=Path)
    parser.add_argument("--browser", choices=("chromium", "webkit"), default="chromium")
    parser.add_argument("--channel", help="Installed Chromium browser channel, e.g. chrome")
    parser.add_argument("--capture", type=Path, help="Save responsive screenshots of the real remote")
    args = parser.parse_args()
    if not (ROOT / "technical-spike/fixtures/initial/A/tone.wav").is_file():
        subprocess.run([sys.executable, str(ROOT / "technical-spike/scripts/generate_fixtures.py")], check=True)
    launcher = [str(args.launcher.resolve())] if args.launcher else [sys.executable, "-m", "karaoke.app"]
    env = dict(os.environ, SDL_AUDIODRIVER="dummy", SDL_AUDIO_DRIVER="dummy")
    with tempfile.TemporaryDirectory(prefix="karaoke-browser-") as folder:
        session = Session(Path(folder), launcher, env)
        try:
            session.launch()
            for title, relative in (("Probe A", "initial/A"), ("Probe B", "staging/B")):
                if not session.rows("SELECT id FROM songs WHERE title=?", (title,)):
                    session.import_chart(ROOT / f"technical-spike/fixtures/{relative}/song.txt")
                    session.wait(lambda _: bool(session.rows("SELECT id FROM songs WHERE title=?", (title,))))
            asyncio.run(test_phones(session, args.browser, args.channel, args.capture))
        except Exception:
            host_snapshot(session, "on failure", logs=True)
            raise
        finally:
            session.close()


if __name__ == "__main__":
    run()
