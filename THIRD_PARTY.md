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

## Descargas de paquetes

Karaoke utiliza libtorrent 2.1.1 para recibir paquetes BitTorrent. El aviso del proyecto se reproduce a continuación. [Fuente de libtorrent](https://github.com/arvidn/libtorrent/tree/56ae8caba38bf154ffc210403cb23f91d0ecaa49)

```text
Copyright (c) 2003-2020, Arvid Norberg
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:

    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in
      the documentation and/or other materials provided with the distribution.
    * Neither the name of Rasterbar Software nor the names of its
      contributors may be used to endorse or promote products derived
      from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
```
