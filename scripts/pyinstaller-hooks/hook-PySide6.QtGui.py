"""The file picker needs native widgets, not PDF rendering or a virtual keyboard.

Avoid shipping their otherwise transitive QtWebEngine/QML/Quick runtimes.
PyInstaller hook API follows the upstream QtGui hook (GPL-2.0-or-later with
PyInstaller bootloader exception); this adaptation is GPL-3.0-only.
"""
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = [(source, target) for source, target in binaries
            if 'qpdf' not in source.lower() and 'qtvirtualkeyboard' not in source.lower()]
