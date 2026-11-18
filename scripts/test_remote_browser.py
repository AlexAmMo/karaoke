#!/usr/bin/env python3
"""Exercise mobile turn menus and room closure against an isolated desktop session.

With Chrome installed, from the repository root:
    uv run --locked --with playwright python scripts/test_remote_browser.py --channel chrome
Add --launcher PATH to exercise an installed package. Without --channel this uses
Playwright's Chromium (install it with uv run --with playwright playwright install chromium).
"""

import argparse
import asyncio
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from playwright.async_api import async_playwright, expect

from test_session import ROOT, Session, read_json


def button(page, name):
    return page.get_by_role("button", name=name, exact=True)


def row(page, title):
    return page.locator("#list li").filter(has=page.get_by_text(title, exact=True))


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
    await page.locator("[data-tab=library]").click()
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
    await expect(page.locator("#feedback")).to_have_text("Turno añadido a la cola")
    await expect(dialog).to_be_visible()
    await expect(dialog.get_by_label("Cantante", exact=True)).to_have_value(new_name)
    await button(dialog, "Guardar cantantes").click()
    await expect(row(observer, title)).to_have_count(1)
    await expect(row(observer, title)).to_contain_text(new_name)
    print(f"PASS: {'retry' if lose_first_response else 'add'} preserved the open menu and edits", flush=True)


async def test_phones(session, browser_type, channel):
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
    async with async_playwright() as playwright:
        browser = await getattr(playwright, browser_type).launch(channel=channel)
        try:
            ana, luis, mar = await asyncio.gather(*(
                join(browser, playwright.devices[model], name, url, code)
                for model, name in (("iPhone 13", "Ana"), ("Pixel 7", "Luis"), ("iPhone SE", "Mar"))
            ))
            await mar.locator("[data-tab=queue]").click()
            await late_add(ana, mar, "Probe A", "Ana y Mar", lose_first_response=False)
            await late_add(luis, mar, "Probe B", "Luis y Mar", lose_first_response=True)

            await mar.context.set_offline(True)
            await expect(mar.locator("#connection")).to_contain_text("Reconectando", timeout=15000)
            await row(luis, "Probe B").get_by_role("button", name=re.compile("Opciones del turno")).click()
            await button(luis, "Quitar de la cola").click()
            await button(luis, "Quitar turno").click()
            await expect(row(ana, "Probe B")).to_have_count(0)
            await expect(button(mar, "Reintentar")).to_be_visible(timeout=25000)
            await expect(mar.locator("#connection")).to_contain_text("No se encuentra el ordenador")
            await mar.context.set_offline(False)
            await expect(mar.locator("#connection")).to_be_hidden(timeout=15000)
            await expect(mar.locator("#list li")).to_have_count(1)
            await expect(row(mar, "Probe A")).to_contain_text("Ana y Mar")
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
        finally:
            await browser.close()


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launcher", type=Path)
    parser.add_argument("--browser", choices=("chromium", "webkit"), default="chromium")
    parser.add_argument("--channel", help="Installed Chromium browser channel, e.g. chrome")
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
            asyncio.run(test_phones(session, args.browser, args.channel))
        finally:
            session.close()


if __name__ == "__main__":
    run()
