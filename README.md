# Karaoke

Karaoke doméstico instalado en el ordenador: UltraStar Deluxe muestra letras, notas y puntuación; un lateral permite preparar biblioteca y próximos turnos sin abrir otra ventana.

La rama de desarrollo incluye búsqueda por artista y título, paquetes opcionales con voz y notas, importación de TXT/ZIP y portadas en biblioteca, búsqueda y cola. Las pruebas y sus condiciones están en [Validación](docs/VALIDACION.md).

## Instalación

Los comandos de esta sección instalan la versión anterior al rediseño del catálogo. Descarga los paquetes de la [prerelease v0.1.0](https://github.com/AlexAmMo/karaoke/releases/tag/v0.1.0), o usa uno de estos comandos. Incluyen el motor y las herramientas necesarias: no necesitas Python ni compiladores.

**macOS**, desde Terminal (Apple Silicon: macOS 26 o posterior; Intel: macOS 15 o posterior):

```sh
curl -fsSL https://raw.githubusercontent.com/AlexAmMo/karaoke/v0.1.0/scripts/install.sh | KARAOKE_VERSION=v0.1.0 bash
```

Se instala en `~/Applications/Karaoke.app`. En Apple Silicon ocupa aproximadamente 192 MB descargados y 412 MB instalado, sin canciones. La firma es ad hoc y no está notarizada; el instalador no desactiva Gatekeeper.

**Windows x64**, desde PowerShell (objetivo: Windows 10 versión 1809 o posterior y Windows 11; controlador OpenGL 2.0 o superior):

```powershell
$env:KARAOKE_VERSION='v0.1.0'; irm https://raw.githubusercontent.com/AlexAmMo/karaoke/v0.1.0/scripts/install.ps1 | iex
```

Se instala en `%LOCALAPPDATA%\Programs\Karaoke` y crea un acceso directo en Inicio. El ejecutable no tiene firma comercial. La validación automatizada usa Windows Server 2022; quedan pendientes pruebas de audio y gráficos en un PC físico. En Mac Intel están comprobados la compilación y el arranque de utilidades; falta validar una sesión gráfica.

Los instaladores verifican SHA-256 y conservan la biblioteca y los ajustes fuera de la app. Esta prerelease no incluye canciones comerciales.

## Una sesión en la versión de desarrollo

1. Abre **Buscar** y escribe el título o el artista. Por ejemplo, `Alex Ubago Sigo Aqui`. También puedes pegar el enlace de un vídeo de YouTube.
2. Pulsa **+** junto a la canción. Karaoke elige una edición compatible y prepara la grabación con voz en segundo plano. Puedes seguir buscando mientras tanto.
3. Abre **Cola** y pulsa **Empezar a cantar**. Al acabar verás la puntuación. Tú decides cuándo empieza el siguiente turno.

Karaoke agrupa las fuentes de una misma canción en una fila. Pulsar el título permite consultar sus ediciones. Las canciones preparadas se conservan en **Biblioteca** para otra sesión. Desde la biblioteca también puedes importar una carpeta, un TXT con su grabación o un ZIP.

Los 39 paquetes de UltraStar Deluxe Songs incluyen mapa, audio y licencia. Los mapas de AllKaraoke y USDB usan el audio identificado por la edición. La aplicación comprueba su correspondencia en segundo plano. Si falta el audio o la comparación resulta dudosa, la cola indica el motivo y permite continuar con otra canción. Para UltraStar España se abre el selector del proveedor dentro de Karaoke. Accede con tu cuenta de UltraStar España y pulsa **Descargar torrent** en la edición. Karaoke recibe el mapa y el audio del mismo paquete, comprueba su sincronía y deja el turno en la cola. Durante la transferencia comparte fragmentos con otros pares. La descarga depende de que haya fuentes disponibles. Puedes pegar el enlace de búsqueda de UltraStar España en **Buscar**. Las fichas sin una vía de descarga integrada se indican por separado. La primera consulta de los índices públicos requiere conexión. En **Ajustes → Cuenta USDB** puedes conectar tu cuenta para ampliar los resultados.

En **Ajustes** puedes cambiar los nombres, el volumen de la música y cuánto se oye tu micrófono en los altavoces. Deja vacío el segundo nombre para cantar solo. **Micrófonos** reúne la selección de entradas y el ajuste de latencia.

## Interfaz y controles

El escenario usa fondo grafito, acento frambuesa, portada protagonista y una tira de canciones. El lateral muestra miniatura, artista y acciones en una sola fila. Las portadas se resuelven en segundo plano desde el paquete, la ficha USDB o el sencillo y el álbum identificados en MusicBrainz. Cuando corresponde se intenta la imagen del artista en Wikimedia Commons. Sin imagen disponible se muestran iniciales. El detalle conserva la procedencia.

Puedes plegar el lateral con la flecha de su encabezado o **Cmd/Ctrl+B**, y recuperarlo con **Mostrar panel**. La canción, la cola y los ajustes siguen activos. **Cmd/Ctrl+1–4** abre Biblioteca, Buscar, Cola o Ajustes. **Tab/Mayús+Tab** recorre el carrusel y los controles; con el carrusel enfocado, las flechas eligen canción e **Intro** la añade a la cola. El canto conserva su proporción 4:3 al ampliar el escenario.

## Desarrollo y ejecución local

Requiere Python 3.12–3.14, [uv](https://docs.astral.sh/uv/), FFmpeg con `ffprobe` y `ffplay`, y las dependencias de compilación de Deluxe. Para macOS con Homebrew:

```sh
brew install fpc automake autoconf pkg-config sdl2 sdl2_image portaudio ffmpeg freetype lua@5.4 sqlite
uv sync --locked
python3 scripts/prepare_engine.py
cd build/engine
./autogen.sh
./configure --without-opencv --without-libprojectM
make macos-standalone-app
cd ../..
uv run karaoke
```

Para construir el paquete completo de macOS: `./scripts/build_macos.sh`. Construcción y empaquetado de Windows: [.github/workflows/build.yml](.github/workflows/build.yml) y [documentación de empaquetado](docs/PACKAGING.md). El instalador de una versión publicada no necesita Python, Homebrew ni un compilador; los comandos de arriba son para desarrollar.

```sh
uv run pytest
python3 technical-spike/scripts/generate_fixtures.py
uv run karaoke --demo --data-dir .runtime/demo
```

`--demo` introduce señales sintéticas etiquetadas para comprobar el detector y la puntuación. No activa micrófonos ni valida latencia física. No se incluyen canciones comerciales.

## Datos y privacidad

La biblioteca, cola y ajustes viven fuera de la aplicación: `~/Library/Application Support/Karaoke` en macOS y `%LOCALAPPDATA%\Karaoke` en Windows. Actualizar o reinstalar la app conserva estos datos. Puedes elegir otra carpeta para futuras canciones. Importar copia los recursos necesarios; borrar desde Karaoke no borra la carpeta de origen.

El motor procesa la señal de micrófono localmente; la aplicación no la graba ni la envía. El catálogo y las descargas sí requieren conexión a sus fuentes. La contraseña de USDB se guarda en Keychain/Credential Manager, nunca en SQLite ni argumentos de procesos. El intercambio entre interfaz y gestor usa archivos temporales en una carpeta privada local. No hay servidor de pago, cuenta de Karaoke ni telemetría propia.

## Arquitectura y licencias

- Motor nativo: [UltraStar Deluxe](https://github.com/UltraStar-Deluxe/USDX), revisión fijada; GPL-2.0-or-later.
- Preparación de mapas y medios: [USDB Syncer](https://github.com/bohning/usdb_syncer), revisión fijada; GPL-3.0-only. Se conserva su lógica de tiempos y transformación.
- Servicio local Python/SQLite; interfaz integrada SDL/Pascal. Comunicación estructurada por archivos atómicos, sin automatizar pulsaciones del juego.
- yt-dlp/FFmpeg obtienen y preparan medios. Las canciones se descargan según disponibilidad y permisos de sus fuentes; no se redistribuyen con la aplicación.

El código propio se publica bajo GPL-3.0-only. Las dependencias conservan sus licencias. Consulta [THIRD_PARTY.md](THIRD_PARTY.md), el manifiesto y los avisos incluidos en cada paquete. No se modifica ni se vuelve a publicar contenido en USDB.
