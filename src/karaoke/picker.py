"""Native folder dialog, isolated from the singing process."""

import json
import sys
from pathlib import Path


def main():
    from PySide6.QtWidgets import QApplication, QFileDialog

    request = json.load(sys.stdin)
    app = QApplication([])
    folder = QFileDialog.getExistingDirectory(
        None, "Importar canciones UltraStar", str(Path.home())
    )
    Path(request["response"]).write_text(json.dumps({"folder": folder}), encoding="utf-8")
    app.quit()


if __name__ == "__main__":
    main()
