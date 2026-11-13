# Construcción y distribución

La aplicación no necesita un servidor. El paquete contiene el motor modificado, el servicio local y los ejecutables de medios. Las canciones, credenciales y datos de sesión no se incluyen en el instalador.

Los scripts de esta carpeta preparan **compilaciones de desarrollo**. Una compilación que termina correctamente no certifica micrófonos físicos, latencia, compatibilidad con todos los ordenadores ni firma de editor. Las pruebas de macOS Apple Silicon, Intel y Windows deben registrarse por separado.

## Construir en macOS

```sh
uv sync --locked
bash scripts/build_macos.sh
uv run python scripts/package_sources.py
uv run python scripts/collect_sources.py
```

El paquete resultante es `dist/Karaoke.app`. Se comprueba que los ejecutables de medios arrancan sin depender de Homebrew en `PATH`, se verifica la firma ad hoc y se auditan las referencias absolutas a bibliotecas. `Contents/Resources/package-audit.json` registra la arquitectura y la mayor versión mínima de macOS declarada por sus binarios; el instalador compara esa versión con el equipo de destino.

La firma ad hoc permite verificar integridad local. **No es una firma Developer ID ni una notarización de Apple.** No se modifica Gatekeeper ni se elimina la cuarentena automáticamente. La distribución sin certificados puede exigir una autorización manual del usuario al abrir la aplicación.

`package_macos.py --skip-python` permite reutilizar un runtime de Python ya generado durante el desarrollo. Para una publicación reproducible, construir desde cero con el archivo `uv.lock` y registrar las versiones de las herramientas nativas.

## Construir en Windows

El trabajo `windows` de `.github/workflows/build.yml` adapta la receta del commit fijado de Deluxe: Windows Server 2022, MSYS2 UCRT64 y Free Pascal 3.2.2. El motor usa captura y reproducción SDL; el fork desactiva BASS y su DLL se excluye del paquete.

El motor necesita un controlador compatible con **OpenGL 2.0 o superior**; se recomienda 3.3. Comprueba la versión real del controlador antes de crear el renderer y muestra un error legible cuando es insuficiente.

El objetivo de esta prerelease es **Windows 10 versión 1809 o posterior y Windows 11, x64**. El mínimo previsto lo determina [Qt 6.11](https://doc.qt.io/qt-6.11/windows.html); no equivale a una prueba en esos equipos. El entorno comprobado es Windows Server 2022, build 20348, en CI. La sesión completa y el hardware en Windows 10/11 siguen pendientes.

Después de compilar el motor:

```powershell
uv run python scripts/package_windows.py --tools C:/msys64/ucrt64/bin
uv run python scripts/package_sources.py
uv run python scripts/collect_windows_sources.py
```

Se genera una carpeta portable `dist/Karaoke` con `karaoke.exe`, motor, runtime de Python y utilidades. El empaquetador recorre las importaciones PE de FFmpeg, FFprobe, FFplay y Deno, copiando sus DLL no pertenecientes a Windows. El empaquetador lee la cabecera PE del motor, el lanzador y todas las DLL/PYD/EXE, y exige AMD64 (0x8664). Los ejecutables de medios se prueban desde la carpeta resultante. No se afirma compatibilidad con Windows ARM.

El runner de Windows Server 2022 ofrece OpenGL 1.1 y ningún dispositivo WASAPI. Para probar el arranque, CI crea una copia temporal del paquete con Mesa llvmpipe y audio SDL `dummy`; registra esos controladores y los hashes del paquete original. El ZIP distribuido conserva las dependencias del producto y utiliza los controladores del ordenador del usuario. Esta prueba de software no valida GPU, audio ni micrófonos físicos. El adaptador de catálogo y las utilidades también se comprueban con un `PATH` que solo incluye el paquete y Windows.

## Instalación de una versión publicada

Los instaladores esperan archivos publicados en Releases de `AlexAmMo/karaoke`; no simulan una descarga cuando no existe una versión. El archivo debe llamarse `Karaoke-VERSION-macos-arm64.zip`, `Karaoke-VERSION-macos-x86_64.zip` o `Karaoke-VERSION-windows-x86_64.zip`, con su archivo `.zip.sha256` al lado.

macOS:

```sh
curl -fsSL https://raw.githubusercontent.com/AlexAmMo/karaoke/v0.1.0/scripts/install.sh | KARAOKE_VERSION=v0.1.0 bash
```

Windows PowerShell:

```powershell
$env:KARAOKE_VERSION='v0.1.0'; irm https://raw.githubusercontent.com/AlexAmMo/karaoke/v0.1.0/scripts/install.ps1 | iex
```

Estos comandos solo son utilizables después de publicar los archivos requeridos. Seleccionan explícitamente la prerelease `v0.1.0`. Si se ejecuta el instalador sin `KARAOKE_VERSION`, consulta la última versión **estable** y excluye las prereleases.

La instalación es por usuario, sin permisos de administrador: `~/Applications/Karaoke.app` en macOS y `%LOCALAPPDATA%\Programs\Karaoke` en Windows. La actualización conserva la biblioteca y los ajustes, verifica SHA-256 y guarda temporalmente la versión anterior para restaurarla si falla el reemplazo. Los hashes detectan corrupción; su autenticidad depende del canal GitHub que sirve también el paquete.

Para desinstalar, borrar la aplicación y el acceso directo. La carpeta de datos no se borra automáticamente. Una eliminación de biblioteca debe ser expresa.

## Fuentes, avisos y publicación

El paquete contiene `licenses/`: avisos de los componentes Python presentes en el entorno, versiones, licencias de Deluxe y de medios, e identificación de fuentes. macOS añade las fórmulas y recibos de Homebrew correspondientes a las utilidades y bibliotecas copiadas. `package_sources.py` incluye el proyecto, el código modificado de Deluxe y el commit exacto de Syncer.

`collect_sources.py` genera un segundo archivo con las fuentes reales de las dependencias de macOS: QtBase y PySide, paquetes Python, CPython y las bibliotecas nativas identificadas a partir de los binarios y fórmulas instaladas. Descarga los tarballs de las versiones concretas y comprueba los SHA-256 de los distribuidores cuando están disponibles. Incluye las recetas de compilación, sus parches y un manifiesto. Si falla alguna descarga, termina con error y conserva el fallo identificado; no declara el conjunto completo.

`collect_windows_sources.py` reúne las descargas originales de la receta de Deluxe y los paquetes fuente de las DLL instaladas por MSYS2, identificados mediante la base de datos de Pacman y los metadatos de los paquetes. Genera además paquetes completos con `makepkg-mingw --allsource`, que obtiene y verifica los recursos externos referidos por cada receta, y registra los archivos y sus hashes. Este recorrido debe validarse en el constructor de Windows; no se da por probado desde macOS.

La publicación de un binario debe incluir ambos archivos de fuentes y sus hashes. El manifiesto `source-manifest.json` y sus entradas pendientes son la evidencia concreta de la recogida. Los enlaces de procedencia no sustituyen los archivos correspondientes.

El workflow sube artefactos de desarrollo y no publica Releases automáticamente. El cierre de una versión requiere revisar fuentes/avisos, realizar la prueba en una máquina limpia de cada plataforma anunciada, comprobar que no contiene datos personales y registrar las limitaciones de firma y audio. El repositorio público puede revisarse y compilarse aunque todavía no exista una versión estable instalable.
