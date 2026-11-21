"""Native folder dialog, isolated from the singing process."""

import json
import sys
from pathlib import Path


def main():
    from PySide6.QtWidgets import QApplication, QFileDialog

    request = json.load(sys.stdin)
    app = QApplication([])
    mode = request.get("mode", "folder")
    if mode == "folder":
        folder = QFileDialog.getExistingDirectory(
            None, "Importar canciones UltraStar", str(Path.home())
        )
    elif mode == "lyrics":
        folder, _ = QFileDialog.getOpenFileName(None, "Elegir letra de la canción", str(Path.home()), "Texto UTF-8 (*.txt)")
    else:
        title, pattern = (
            ("Elegir grabación", "Audio (*.mp3 *.ogg *.opus *.m4a *.flac *.wav *.aac);;Todos (*)")
            if mode == "audio"
            else ("Elegir paquete o mapa", "UltraStar (*.txt *.zip);;Todos (*)")
        )
        folder, _ = QFileDialog.getOpenFileName(None, title, str(Path.home()), pattern)
    Path(request["response"]).write_text(json.dumps({"folder": folder}), encoding="utf-8")
    app.quit()


if __name__ == "__main__":
    main()
