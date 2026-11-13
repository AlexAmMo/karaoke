# Componentes de terceros

El código propio de Karaoke es GPL-3.0-only, compatible con la licencia GPL-2.0-or-later de UltraStar Deluxe y GPL-3.0-only de USDB Syncer. Las dependencias conservan sus autores, licencias y condiciones; no se relicencian bajo el nombre de Karaoke.

| Componente | Revisión usada | Fuente |
|---|---|---|
| UltraStar Deluxe | `8b9d9e08eca997d2e3fe789084fbac136988f276` | https://github.com/UltraStar-Deluxe/USDX |
| USDB Syncer | `1690c6d7505701047b245a3470867c0b3ddae01d` | https://github.com/bohning/usdb_syncer |
| Dependencias Python, incluido yt-dlp/PySide6 | Versiones y hashes en `uv.lock` | Sus distribuciones y repositorios originales |
| SDL, FFmpeg, PortAudio y bibliotecas nativas | Inventario de cada paquete | Avisos, manifiesto y archivo de fuentes del paquete |

El parche de Deluxe y el código de la interfaz están en `patches/` y `native/`. No se incluye BASS en los paquetes propios de Windows: se seleccionan los backends SDL existentes en Deluxe. macOS usa el backend de captura disponible en su construcción (PortAudio), con reproducción SDL. Esta selección no equivale a una validación física de ambos sistemas.

Los scripts de empaquetado recopilan avisos, manifiestos y fuentes correspondientes; los artefactos de fuentes deben acompañar a los binarios publicados. `scripts/package_sources.py` incluye el código de la app, el motor modificado y Syncer; `scripts/collect_sources.py` obtiene las fuentes de dependencias con verificaciones. Consulta `docs/PACKAGING.md` y el informe de cobertura de fuentes para límites concretos. Las bibliotecas del sistema operativo no se redistribuyen.

Los mapas y medios descargados pertenecen a sus respectivos autores y no forman parte de este repositorio. Las muestras de pruebas son señales originales generadas por `technical-spike/scripts/generate_fixtures.py`.
