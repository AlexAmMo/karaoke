# Karaoke

Karaoke doméstico instalado en el ordenador: UltraStar Deluxe muestra letras, notas y puntuación; un lateral permite preparar biblioteca y próximos turnos sin abrir otra ventana.

**Versión de desarrollo 0.1.0.** La app empaquetada supera 17 comprobaciones de sesión en macOS Apple Silicon. Las 55 pruebas Python pasan localmente y en CI sobre macOS, Linux y Windows. Windows supera una prueba de arranque y cierre con gráficos y audio simulados. Las pruebas sintéticas no sustituyen una sesión con uno o dos micrófonos por cable; las descargas con cuenta USDB también están pendientes de validación real. El estado verificable está en [docs/VALIDACION.md](docs/VALIDACION.md).

## Instalación

Descarga los paquetes de la [prerelease v0.1.0](https://github.com/AlexAmMo/karaoke/releases/tag/v0.1.0), o usa uno de estos comandos. Incluyen el motor y las herramientas necesarias: no necesitas Python ni compiladores.

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

## Uso

1. Abre **Karaoke**. En **Ajustes**, introduce los nombres; deja el segundo vacío para cantar solo.
2. Conecta el micrófono, pulsa **Detectar micrófonos** y asigna dispositivo/canal a cada jugador. Prueba la señal y sube el retorno gradualmente si quieres oír tu voz.
3. Importa una carpeta UltraStar preparada desde **Biblioteca**, o conecta tu cuenta gratuita de [USDB](https://usdb.animux.de/) en **Ajustes** y busca artista/título en **Buscar**.
4. Añade un turno. La preparación ocurre en segundo plano. En **Cola**, pulsa **Empezar turno** cuando esté listo.
5. Al terminar verás los resultados. Tú decides cuándo empieza la siguiente canción.

La búsqueda acepta `artista - título` y enlaces de YouTube. Un enlace ofrece candidatos de mapas; no cambia silenciosamente el audio asociado al mapa. No es un buscador general de vídeos.

La voz original del paquete se conserva. **Buscar instrumental existente** obtiene candidatos; permite preescucha al principio, centro y final y exige confirmar la correspondencia. Ni el título ni una duración parecida certifican la afinación o la sincronía. No se generan notas ni se separa voz con IA.

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
