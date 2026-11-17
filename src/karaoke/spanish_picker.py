"""An in-app window for selecting an edition on the publisher's own website."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlencode, urlsplit


def search_url(song):
    return "https://ultrastar-es.org/es/canciones?" + urlencode(
        {"artista": song["artist"], "cancion": song["title"]}
    )


def publisher_url(url):
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and parsed.hostname in {"ultrastar-es.org", "www.ultrastar-es.org", "tr.ultrastar-es.org"}
        and port in (None, 443)
    )


def download_kind(filename, mime):
    ext = Path(filename).suffix.lower()
    if ext == ".torrent" or mime == "application/x-bittorrent":
        return "torrent"
    if ext == ".zip" or mime == "application/zip":
        return "zip"
    return ""


def show(request):
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView

    directory = Path(request["destination"])
    profile_dir = Path(request["profile"])
    profile_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Karaoke")
    window = QWidget()
    window.setWindowTitle("Karaoke · UltraStar España")
    window.resize(980, 700)
    box = QVBoxLayout(window)
    status = QLabel(
        "Accede con tu cuenta de UltraStar España y elige «Descargar torrent». "
        "Karaoke descarga el paquete y comparte fragmentos mientras lo recibe."
    )
    status.setWordWrap(True)
    box.addWidget(status)
    browser = QWebEngineView(window)
    box.addWidget(browser, 1)
    profile = QWebEngineProfile("UltraStar España", app)
    profile.setPersistentStoragePath(str(profile_dir))
    profile.setCachePath(str(profile_dir / "cache"))

    class PublisherPage(QWebEnginePage):
        def acceptNavigationRequest(self, url, kind, main_frame):
            if main_frame and not publisher_url(url.toString()):
                status.setText("Esta ventana solo abre páginas de UltraStar España.")
                return False
            return super().acceptNavigationRequest(url, kind, main_frame)

    page = PublisherPage(profile, browser)
    browser.setPage(page)
    page.settings().setAttribute(
        QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, False
    )
    page.newWindowRequested.connect(
        lambda event: (
            browser.setUrl(event.requestedUrl())
            if publisher_url(event.requestedUrl().toString())
            else None
        )
    )
    result = {"status": "cancelled"}
    active = None

    def download(item):
        nonlocal active
        kind = download_kind(item.suggestedFileName(), item.mimeType())
        if active or not publisher_url(item.url().toString()) or not kind:
            item.cancel()
            status.setText("Elige el torrent o ZIP de la edición completa, con audio y notas.")
            return
        limit = 4 * 1024**2 if kind == "torrent" else 2 * 1024**3
        if item.totalBytes() > limit:
            item.cancel()
            status.setText("El archivo de esta edición supera el tamaño admitido.")
            return
        active = item
        item.setDownloadDirectory(str(directory))
        item.setDownloadFileName("edition." + kind)

        def changed():
            nonlocal active
            if item.receivedBytes() > limit:
                item.cancel()
            elif item.isFinished():
                if item.state() == item.DownloadState.DownloadCompleted:
                    result.update(status="selected", kind=kind)
                    window.close()
                else:
                    active = None
                    status.setText(
                        "La descarga se ha interrumpido. Puedes volver a elegir la edición."
                    )

        item.receivedBytesChanged.connect(changed)
        item.isFinishedChanged.connect(changed)
        status.setText("Recibiendo la edición en Karaoke…")
        item.accept()

    profile.downloadRequested.connect(download)
    browser.setUrl(QUrl(search_url(request["song"])))
    window.show()
    app.exec()
    if active and not active.isFinished():
        active.cancel()
    return result


def probe():
    """Exercise the packaged browser renderer and torrent engine without a provider account."""
    import libtorrent
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from PySide6.QtWebEngineWidgets import QWebEngineView

    app = QApplication([])
    browser = QWebEngineView()
    result = {"browser": False, "torrent": bool(libtorrent.version)}

    def loaded(ok):
        result["browser"] = bool(ok and browser.title() == "Karaoke")
        app.quit()

    browser.loadFinished.connect(loaded)
    browser.setHtml("<title>Karaoke</title>")
    QTimer.singleShot(20000, app.quit)
    app.exec()
    return result


def main():
    request = json.load(sys.stdin)
    result = probe() if request.get("probe") else show(request)
    Path(request["response"]).write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
