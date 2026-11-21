# Karaoke

Karaoke doméstico para macOS y Windows. UltraStar Deluxe muestra la letra, las notas y la puntuación. Desde el lateral o desde un móvil puedes buscar la próxima canción mientras alguien canta.

La versión 0.3 reúne el catálogo y las descargas en Buscar. Admite hasta diez cantantes, entradas por cable y móviles, y generación local de borradores desde YouTube. Las pruebas y sus condiciones están en [Validación](docs/VALIDACION.md).

## Instalación

Instala la versión preliminar 0.3.1 con el comando de tu plataforma o elige el paquete de tu equipo. [Descargas de v0.3.1](https://github.com/AlexAmMo/karaoke/releases/tag/v0.3.1)

**macOS**, desde Terminal (Apple Silicon: macOS 26 o posterior; Intel: macOS 15 o posterior):

```sh
curl -fsSL https://raw.githubusercontent.com/AlexAmMo/karaoke/v0.3.1/scripts/install.sh | KARAOKE_VERSION=v0.3.1 bash
```

Se instala en `~/Applications/Karaoke.app`. La firma es ad hoc y no está notarizada; el instalador no desactiva Gatekeeper.

**Windows x64**, desde PowerShell (objetivo: Windows 10 versión 1809 o posterior y Windows 11; controlador OpenGL 2.0 o superior):

```powershell
$env:KARAOKE_VERSION='v0.3.1'; irm https://raw.githubusercontent.com/AlexAmMo/karaoke/v0.3.1/scripts/install.ps1 | iex
```

Se instala en `%LOCALAPPDATA%\Programs\Karaoke` y crea un acceso directo en Inicio. El ejecutable no tiene firma comercial. La validación automatizada usa Windows Server 2022; quedan pendientes pruebas de audio y gráficos en un PC físico. El paquete Intel también se ha probado con Rosetta en Apple Silicon.

Los instaladores verifican SHA-256 y conservan la biblioteca y los ajustes fuera de la app. Las canciones se preparan durante la búsqueda.

## Una sesión de karaoke

1. Abre **Buscar** y escribe el título o el artista. Por ejemplo, `Alex Ubago Sigo Aqui`. También puedes pegar el enlace de un vídeo de YouTube.
2. Pulsa **+** junto a la canción. Karaoke elige una edición compatible y prepara la grabación con voz en segundo plano. Puedes seguir buscando mientras tanto.
3. Abre **Cola** y pulsa **Empezar a cantar**. Al acabar verás la puntuación. Tú decides cuándo empieza el siguiente turno.

Al cantar, la barra de la canción indica la nota que debes alcanzar. Si ves tu trazo semitransparente por encima, baja el tono. Si aparece por debajo, súbelo. Los aciertos se iluminan sobre la barra. El trazo se interrumpe cuando el micrófono deja de detectar un tono.

Karaoke agrupa las fuentes de una misma canción en una fila. Pulsar el título permite consultar sus ediciones. **Solo descargadas** reúne las copias que ya puedes cantar. Si prefieres guardar la canción para otro día, pulsa su título y elige **Solo descargar**. En **Sesión → Descargas e importación** puedes importar una carpeta, un TXT con su grabación o un ZIP.

Los 39 paquetes de UltraStar Deluxe Songs incluyen mapa, audio y licencia. Los mapas de AllKaraoke y USDB usan el audio identificado por la edición. La aplicación comprueba su correspondencia en segundo plano. Si falta el audio o la comparación resulta dudosa, la cola indica el motivo y permite continuar con otra canción. Para UltraStar España se abre el selector del proveedor dentro de Karaoke. Accede con tu cuenta de UltraStar España y pulsa **Descargar torrent** en la edición. Karaoke recibe el mapa y el audio del mismo paquete, comprueba su sincronía y deja el turno en la cola. Durante la transferencia comparte fragmentos con otros pares. La descarga depende de que haya fuentes disponibles. Puedes pegar el enlace de búsqueda de UltraStar España en **Buscar**. Las fichas sin una vía de descarga integrada se indican por separado. La primera consulta de los índices públicos requiere conexión. En **Ajustes → Cuenta USDB** puedes conectar tu cuenta para ampliar los resultados.

En **Sesión → Cantantes y entradas** puedes crear hasta diez perfiles y asignar una entrada a cada uno. Varias personas pueden compartir un micro en turnos distintos. En la cola puedes cambiar quién canta y con qué entrada. En la ficha del cantante se ajustan el retorno y la compensación temporal por dispositivo. Si percibes eco, baja el retorno o usa la monitorización directa de tu interfaz de audio.

En **Sesión → Precisión de afinación** puedes elegir **Flexible** (hasta dos semitonos por encima o por debajo), **Normal** (un semitono de margen, valor inicial) o **Estricta** (el motor debe detectar la nota indicada). El mando móvil ofrece el mismo selector en **Ajustes de la sesión**. El nivel queda guardado y se aplica a los cantantes desde el siguiente turno.

## Mando desde varios móviles

En **Cola** o **Ajustes**, pulsa **Conectar móviles**. Conecta los teléfonos al mismo wifi que el ordenador (el ordenador también puede estar conectado al router por cable). Cada persona escanea el QR con la cámara, abre la página y escribe su nombre. Para entrar a mano, abre la dirección que aparece bajo el QR e introduce el código. Usa una red de confianza: todos los invitados conectados pueden gestionar los turnos y la reproducción.

Cada móvil tiene su buscador. La biblioteca, las descargas, la música y la cola pertenecen al ordenador. Puedes buscar mientras otra persona canta, añadir tu turno, moverlo, cambiar los cantantes, pausar, reanudar y terminar la canción desde el navegador. Puedes cantar con un micro del ordenador o pulsar **Usar este móvil como micrófono** en los ajustes del mando. Mantén abierta la página de captura mientras cantas. Las solicitudes de UltraStar España que requieran identificación se completan en Karaoke desde la cola del ordenador.

Si no se abre la página, comprueba que el teléfono esté en el wifi de casa y que el sistema permita a Karaoke recibir conexiones en la red privada. Una red de invitados puede aislar los dispositivos entre sí. Si aparecen varias direcciones, elige la de la red que compartes con los móviles. Cerrar el mando desde el PC invalida la invitación y permite continuar con la cola local.

## Interfaz y controles

El escenario muestra el próximo turno sobre verde tinta, con la acción principal en melocotón. El lateral muestra miniatura, artista y acciones en una sola fila. Las portadas se resuelven en segundo plano desde el paquete, la ficha USDB o el sencillo y el álbum identificados en MusicBrainz. Cuando corresponde se intenta la imagen del artista en Wikimedia Commons. Sin imagen disponible se muestran iniciales. El detalle conserva la procedencia.

Puedes plegar el lateral con la flecha de su encabezado o **Cmd/Ctrl+B**, y recuperarlo con **Mostrar panel**. La canción, la cola y los ajustes siguen activos. **Cmd/Ctrl+1** o **2** abre Buscar, **3** abre Cola y **4** abre Sesión. **Tab/Mayús+Tab** recorre los controles. En una fila, selecciona `+` y pulsa **Intro** para añadir un turno. El canto conserva su proporción 4:3 al ampliar el escenario.

## Generar una canción desde YouTube

Pega el enlace en **Buscar** para localizar un mapa de esa grabación. Si falta, elige **Crear un borrador con este vídeo**. También puedes abrir **Sesión → Generar desde YouTube**. La primera vez Karaoke instala el entorno y los modelos en tu ordenador. Esta opción ocupa varios GB. El procesamiento se pausa mientras alguien canta.

El generador admite vídeos individuales de hasta 15 minutos y descargas de hasta 200 MiB. YouTube debe permitir que ese ordenador obtenga la grabación. Como referencia, un Mac M4 con 16 GiB y modelos ya instalados preparó «Sigo Aquí» (3 min 45 s) a partir de su enlace en 8 min 38 s con otros análisis en marcha. El editor mostró 435 notas. El tiempo depende de la duración, de la densidad de la letra y del equipo. [Prueba desde el enlace hasta el canto](docs/validation/generacion-y-canto.json)

Karaoke conserva la mezcla con la voz original, separa la voz para el análisis y calcula letra, sílabas, tiempos y melodía. Intenta aprovechar los subtítulos del autor que coincidan en palabras y tiempos con la interpretación. En el método de alineación cantada, Karaoke consulta LRCLIB con el título y el artista para buscar una letra que coincida con la grabación. Puedes desactivar la consulta o aportar tu propio TXT. **Alineación cantada** utiliza modelos disponibles para uso no comercial.

Si la app puede contrastar la generación con un mapa independiente del mismo vídeo, comprueba automáticamente la letra, la melodía y la sincronía con el audio. La puntuación respeta los silencios de esa edición y las sílabas sin un tono corroborado quedan en estilo libre. Una edición que supera las comprobaciones queda lista para cantar. Cuando falta esa evidencia, abre **Escuchar y revisar**. Puedes saltar a los pasajes donde los modelos discrepan, escuchar una guía de tono sobre la grabación y corregir la letra, la nota o su posición. **Aprobar para cantar** guarda esa edición en Buscar. Los resultados dependen de la grabación y pueden necesitar correcciones, especialmente con voces superpuestas y rap.

## Micrófonos de los móviles

Conecta los teléfonos a la misma red, abre **Sesión → Conectar móviles** y escanea el QR. El mando funciona en la red local. Para activar un micro desde una sala HTTP, el mando abre una página HTTPS estática que solicita permiso al navegador. La página necesita internet para cargarse. El audio y la negociación de la conexión permanecen entre teléfono y ordenador. El retorno inicial del micro móvil está apagado.

En una red con HTTPS propio, el anfitrión puede definir `KARAOKE_TLS_CERT`, `KARAOKE_TLS_KEY` y `KARAOKE_TLS_HOST`. El nombre debe apuntar al ordenador y el teléfono debe confiar en el certificado. En ese caso el propio mando solicita el permiso y puede funcionar sin acceso a internet.

## Desarrollo y ejecución local

Requiere Python 3.12 o 3.13, [uv](https://docs.astral.sh/uv/), FFmpeg con `ffprobe` y `ffplay`, y las dependencias de compilación de Deluxe. Para macOS con Homebrew:

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

El ordenador procesa la voz en memoria. Al activar un micrófono móvil, el teléfono envía audio cifrado directamente al ordenador por la red local. El catálogo y las descargas sí requieren conexión a sus fuentes. La contraseña de USDB se guarda en Keychain/Credential Manager, nunca en SQLite ni argumentos de procesos. El intercambio entre interfaz y gestor usa archivos temporales en una carpeta privada local. No hay servidor de pago, cuenta de Karaoke ni telemetría propia.

## Arquitectura y licencias

- Motor nativo: [UltraStar Deluxe](https://github.com/UltraStar-Deluxe/USDX), revisión fijada; GPL-2.0-or-later.
- Preparación de mapas y medios: [USDB Syncer](https://github.com/bohning/usdb_syncer), revisión fijada; GPL-3.0-only. Se conserva su lógica de tiempos y transformación.
- Servicio local Python/SQLite; interfaz integrada SDL/Pascal. Comunicación estructurada por archivos atómicos, sin automatizar pulsaciones del juego.
- yt-dlp/FFmpeg obtienen y preparan medios. Las canciones se descargan según disponibilidad y permisos de sus fuentes; no se redistribuyen con la aplicación.

El código propio se publica bajo GPL-3.0-only. Las dependencias conservan sus licencias. Consulta [THIRD_PARTY.md](THIRD_PARTY.md), el manifiesto y los avisos incluidos en cada paquete. No se modifica ni se vuelve a publicar contenido en USDB.
