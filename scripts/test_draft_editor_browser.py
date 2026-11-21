"""Exercise playback, editing and approval of a local generated draft in two browsers."""

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from karaoke.draft_review import DraftEditor
from karaoke.service import Service


def check(pw, engine, source):
    with tempfile.TemporaryDirectory() as temp:
        host = Service(Path(temp))
        try:
            lab = host.lab
            uid = lab.enqueue("IA0uSub1xy4", "Prueba de edición", "Artista", "es", "quality")
            folder = lab.root / uid / "draft"
            shutil.copytree(source, folder)
            manifest = folder / "generation.json"
            data = json.loads(manifest.read_text())
            data.setdefault("diagnostics", {})["review_regions"] = [
                {"start": 22.0, "reasons": ["pitch_disagreement"]}
            ]
            manifest.write_text(json.dumps(data), encoding="utf8")
            host.store.execute("UPDATE drafts SET state='review' WHERE id=?", (uid,))
            ed = DraftEditor(lab, uid)
            lab.editor = ed
            kwargs = {"channel": "chrome", "args": ["--mute-audio"]} if engine == "chromium" else {}
            with getattr(pw, engine).launch(**kwargs) as browser:
                page = browser.new_page(viewport={"width": 1024, "height": 768})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(ed.url)
                expect(
                    page.get_by_role("button", name="Escuchar el siguiente pasaje")
                ).to_be_visible()
                controls = page.get_by_label("Altura UltraStar", exact=True)
                expect(controls.first).to_be_enabled()
                count = controls.count()
                page.get_by_label("Oír la melodía").check()
                page.get_by_role("button", name="Escuchar el siguiente pasaje").click()
                page.wait_for_function(
                    "document.querySelector('audio').currentTime >= 21.5 && !document.querySelector('audio').paused"
                )
                page.locator("audio").evaluate("(a) => a.pause()")
                pitch = int(controls.first.input_value())
                controls.first.fill(str(pitch + 1))
                page.get_by_role("button", name="Guardar borrador").click()
                expect(page.get_by_role("status")).to_contain_text("Borrador guardado")
                page.reload()
                expect(controls.first).to_have_value(str(pitch + 1))
                page.get_by_role("button", name="Aprobar para cantar").click()
                expect(page.get_by_role("status")).to_contain_text("edición revisada")
                expect(controls.first).to_be_disabled()
                assert (
                    lab.row(uid)["state"] == "approved"
                    and len(host.store.rows("SELECT * FROM songs")) == 1
                    and not errors
                ), errors
                return {
                    "engine": engine,
                    "editable_notes": count,
                    "enabled_tone_guide": True,
                    "played_original_at_flagged_time": True,
                    "saved_edit_survived_reload": True,
                    "approved_song_in_library": True,
                    "page_errors": errors,
                }
        finally:
            host.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "draft",
        type=Path,
        help="Generated draft with song.txt, generation.json and at least 23 seconds of audio",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with sync_playwright() as pw:
        results = [check(pw, engine, args.draft) for engine in ("chromium", "webkit")]
    report = json.dumps(results, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    print(report, end="")
