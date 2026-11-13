# Construcción y distribución

La aplicación no necesita un servidor. El paquete contiene el motor modificado, el servicio local y los ejecutables de medios. Las canciones, credenciales y datos de sesión no se incluyen en el instalador.

Los scripts de esta carpeta preparan **compilaciones de desarrollo**. Una compilación que termina correctamente no certifica micrófonos físicos, latencia, compatibilidad con todos los ordenadores ni firma de editor. Las pruebas de macOS Apple Silicon, Intel y Windows deben registrarse por separado.

## Construir en macOS

```sh
uv sync --locked
bash scripts/build_macos.sh
uv run python scripts/package_macos.py
uv run python scripts/package_sources.py
```

El paquete resultante es `dist/Karaoke.app`. Se comprueba que los ejecutables de medios arrancan sin depender de Homebrew en `PATH`, se verifica la firma ad hoc y se auditan las referencias absolutas a bibliotecas. `Contents/Resources/package-audit.json` registra la arquitectura y la mayor versión mínima de macOS declarada por sus binarios; el instalador compara esa versión con el equipo de destino.

La firma ad hoc permite verificar integridad local. **No es una firma Developer ID ni una notarización de Apple.** No se modifica Gatekeeper ni se elimina la cuarentena automáticamente. La distribución sin certificados puede exigir una autorización manual del usuario al abrir la aplicación.

`package_macos.py --skip-python` permite reutilizar un runtime de Python ya generado durante el desarrollo. Para una publicación reproducible, construir desde cero con el archivo `uv.lock` y registrar las versiones de las herramientas nativas.

## Construir en Windows

El trabajo `windows` de `.github/workflows/build.yml` adapta la receta del commit fijado de Deluxe: Windows Server 2022, MSYS2 UCRT64 y Free Pascal 3.2.2. El motor usa captura y reproducción SDL; el fork desactiva BASS y su DLL se excluye del paquete.

Después de compilar el motor:

```powershell
uv run python scripts/package_windows.py --tools C:/msys64/ucrt64/bin
uv run python scripts/package_sources.py
```

Se genera una carpeta portable `dist/Karaoke` con `karaoke.exe`, motor, runtime de Python y utilidades. El empaquetador recorre las importaciones PE de FFmpeg, FFprobe, FFplay y Deno, copiando sus DLL no pertenecientes a Windows. Los ejecutables de medios se prueban desde la carpeta resultante. No se afirma compatibilidad con Windows ARM.

## Instalación de una versión publicada

Los instaladores esperan archivos publicados en Releases de `AlexAmMo/karaoke`; no simulan una descarga cuando no existe una versión. El archivo debe llamarse `Karaoke-VERSION-macos-arm64.zip`, `Karaoke-VERSION-macos-x86_64.zip` o `Karaoke-VERSION-windows-x86_64.zip`, con su archivo `.zip.sha256` al lado.

macOS:

```sh
curl -fsSL https://raw.githubusercontent.com/AlexAmMo/karaoke/main/scripts/install.sh | bash
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/AlexAmMo/karaoke/main/scripts/install.ps1 | iex
```

Estos comandos solo son utilizables después de publicar los archivos requeridos. Para una prerelease o versión concreta, establecer `KARAOKE_VERSION=v0.1.0` antes de ejecutar el instalador. El valor predeterminado consulta la última versión **estable**.

La instalación es por usuario, sin permisos de administrador: `~/Applications/Karaoke.app` en macOS y `%LOCALAPPDATA%\Programs\Karaoke` en Windows. La actualización conserva la biblioteca y los ajustes, verifica SHA-256 y guarda temporalmente la versión anterior para restaurarla si falla el reemplazo. Los hashes detectan corrupción; su autenticidad depende del canal GitHub que sirve también el paquete.

Para desinstalar, borrar la aplicación y el acceso directo. La carpeta de datos no se borra automáticamente. Una eliminación de biblioteca debe ser expresa.

## Fuentes, avisos y publicación

El paquete contiene `licenses/`: avisos de los componentes Python presentes en el entorno, versiones, licencias de Deluxe y de medios, e identificación de fuentes. macOS añade las fórmulas y recibos de Homebrew correspondientes a las utilidades y bibliotecas copiadas. `package_sources.py` incluye el proyecto, el código modificado de Deluxe y el commit exacto de Syncer.

Antes de publicar binarios se debe comprobar la disponibilidad de **todas las fuentes correspondientes** de los componentes copyleft distribuidos, incluyendo Qt, FFmpeg y sus códecs y bibliotecas nativas. El archivo de fuentes de la aplicación no incluye por sí solo todas esas dependencias. Los enlaces y las fórmulas documentan procedencia; no se presentan como un reemplazo automático de las obligaciones de redistribución.

El workflow sube artefactos de desarrollo y no publica Releases automáticamente. El cierre de una versión requiere revisar fuentes/avisos, realizar la prueba en una máquina limpia de cada plataforma anunciada, comprobar que no contiene datos personales y registrar las limitaciones de firma y audio. El repositorio público puede revisarse y compilarse aunque todavía no exista una versión estable instalable.
