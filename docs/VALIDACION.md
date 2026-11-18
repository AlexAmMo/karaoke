# Validación de la implementación

Estado de la prerelease [v0.1.0](https://github.com/AlexAmMo/karaoke/releases/tag/v0.1.0), publicada el 13 de noviembre de 2026. Este documento distingue código implementado, pruebas de software y comprobaciones que requieren equipos o cuentas externos.

## Comprobado localmente

- Compilación de Deluxe modificado en macOS Apple Silicon y verificación de firma ad hoc.
- Biblioteca/cola SQLite, alias de fuentes, deduplicación, staging, validación de recursos, recuperación de trabajos y turnos.
- 55 pruebas automatizadas del backend correctas. Incluyen procesamiento real TXT/SQLite/FFmpeg/Syncer con fronteras remotas sustituidas por datos de prueba. No simulan el resultado de todos los componentes. Las cinco regresiones más recientes comprueban guardar una versión elegida desde un enlace sin crear turno y descartar resultados tardíos al cambiar de instrumental.
- Error de autenticación USDB explícito desde el proceso real del adaptador, sin credenciales; no se confunde con catálogo vacío.
- Navegación de biblioteca, selección, añadir turno e inicio desde teclado en la app real.
- Canto con dos señales sintéticas: resultado 10.000 frente a 0. Escribir espacios y pegar `canción española` en el campo enfocado conserva el canto y los acentos.
- Inspección visual a 1280×800 y 1000×640. Las capturas están en `.impeccable/review/`.
- Cierre de la ventana mediante el atajo de sistema sin una confirmación oculta del menú anterior.

La automatización CUA de ratón entregó coordenadas SDL obsoletas respecto a su indicador visual. Se observó selección real de una fila mediante el ratón, pero esta evidencia no certifica todos los objetivos de clic. No se cambió el cálculo de coordenadas basándose en esa inyección inconsistente.

## Sesión integral

`scripts/test_session.py` completó 17/17 comprobaciones en 32,25 segundos (367 muestras). `docs/evidence/session-macos.json` contiene la evidencia: ganancias distintas producen picos 4000/800, silenciar conserva nivel de captura y subida de puntos, importar C durante A conserva el canto, los resultados no arrancan otro turno, y reabrir recupera B/C en orden sin autoplay. Se verificó también exclusión de segunda instancia.

## Pendiente antes de declarar una V1 estable

- Micrófono por cable real, dos dispositivos/canales, niveles, retorno audible, latencia, realimentación y sincronía durante una sesión prolongada. El usuario todavía no dispone del micrófono.
- Descarga autenticada de canciones reales de USDB, prueba de enlaces y revisión musical de instrumentales. No se ha usado ni inventado una cuenta del usuario.
- Sesión completa de canto y prueba física en Windows 10/11. El arranque con controladores por software en CI se registra más abajo.
- Instalación en máquinas limpias y comportamiento de Gatekeeper/SmartScreen. La firma local ad hoc no es una notarización de Apple ni firma comercial de Windows.
- La compilación local utiliza bibliotecas que requieren macOS 26. No demuestra compatibilidad con versiones anteriores. Los paquetes de CI deben declarar su mínimo efectivo a partir de su propio inventario.
- La interfaz SDL no expone semántica completa a lectores de pantalla. Tiene foco y operación por teclado, pero no se declara accesibilidad total.

La generación de mapas por IA, móviles, dúos con partes diferentes y segunda pantalla siguen fuera de V1. Los mapas de tiempos relativos requieren conversión previa; se rechazan con explicación. Si Syncer necesita escoger un audio alternativo ambiguo de comentarios, se rechaza y se pide otra fuente/importación compatible.

## Revisión de interfaz

El revisor independiente de Impeccable resolvió cuatro defectos: Enter ya no cambia un slider, seleccionar todo conserva el texto, Tab/Shift+Tab recorren pestañas/transporte/controles y el mensaje de preparación cambia a canto al confirmarlo el motor. La segunda revisión dio `ship` para esos cuatro hallazgos y el alcance visual revisado; no certifica Windows, hardware ni lectores de pantalla. Capturas finales: `.impeccable/review/session-final-1280.jpg` y `selection-1280.jpg`.

## Paquete autónomo de macOS

La aplicación congelada de la revisión `c2d56d8` completó de nuevo las 17/17 comprobaciones con `PATH=/usr/bin:/bin`, sin depender de Homebrew para ejecutar medios o el motor. La [evidencia del paquete](evidence/session-frozen-macos.json) registra 35,05 segundos, 363 muestras, los ejecutables utilizados y sus hashes. El controlador de pruebas se ejecuta con Python de desarrollo; la app, el motor y sus dependencias son los del paquete. Estas 17 comprobaciones integrales complementan las 55 pruebas del backend; siguen usando entrada sintética y no sustituyen la validación de micrófonos ni del catálogo autenticado.

La revisión `c2d56d8` pasa las 55 pruebas Python en GitHub Actions sobre macOS, Ubuntu y Windows Server 2022 ([ejecución 43475448571](https://github.com/AlexAmMo/karaoke/actions/runs/43475448571)); también pasan localmente en macOS. Este resultado no equivale a probar el audio físico ni el renderizado Windows.

## Instalación en el Mac de desarrollo

La instalación inicial se abrió mediante el mecanismo normal de lanzamiento de aplicaciones, con biblioteca vacía y modo sintético desactivado. El selector nativo de carpetas abre y permite cancelar sin importar contenido.

Después de publicar v0.1.0, se ejecutó el comando público de README (`curl …/v0.1.0/scripts/install.sh | KARAOKE_VERSION=v0.1.0 bash`) en este Mac. El script descargó el ZIP público, verificó su SHA-256, firma ad hoc y mínimo de macOS, y reinstaló `~/Applications/Karaoke.app` con código de salida 0. Los dos archivos SQLite existentes conservaron exactamente sus hashes antes de volver a abrir la app. El launcher devuelve `Karaoke 0.1.0`; el motor vuelve a `idle`, sin error y con modo sintético desactivado. La app queda abierta para el usuario. [Evidencia de instalación](validation/installation-macos.json).

Esta prueba usa el Mac de desarrollo: no es una instalación en un Mac limpio y no verifica la política de cuarentena de una descarga nueva de navegador.

## Arranque de Windows por software

La revisión `ae0f0eb` supera el arranque del motor y el cierre limpio en Windows Server 2022 en 5,91 segundos ([ejecución 43483165075](https://github.com/AlexAmMo/karaoke/actions/runs/43483165075)). Se verifican también la comunicación UTF-8 por stdin con el proveedor congelado, los ejecutables de medios con PATH aislado y la arquitectura AMD64 de los binarios.

El runner carece de salida WASAPI y solo ofrece OpenGL 1.1 con su controlador básico. La prueba utiliza una copia temporal con Mesa 26.2.3/llvmpipe (OpenGL 4.6) y SDL `dummy`; esos controladores se registran expresamente y no se añaden al ZIP del producto. El motor llega a `idle`, con ventana 1280×800, modo sintético y error vacío; sale con código 0. Esto no valida una sesión cantada, una GPU real ni el audio físico de Windows. El equipo del usuario necesita un controlador OpenGL 2.0 o superior.

La construcción de Mac Intel también está comprobada en CI, con mínimo declarado macOS 15 y fuentes reunidas. Su alcance de validación es compilación, firma y utilidades; la sesión gráfica en Intel queda pendiente. Evidencia: `docs/validation/packaging-macos-intel.json`.

## Instalación pública en Windows

El comando PowerShell publicado para v0.1.0 supera la [ejecución 43489268529](https://github.com/AlexAmMo/karaoke/actions/runs/43489268529), en Windows Server 2022 con PowerShell 7.6.9. Descarga sin token el script del tag público y el ZIP de la release; el instalador verifica SHA-256. El launcher instalado devuelve `Karaoke 0.1.0` y sale con código 0. Se comprueban el destino y el directorio del acceso directo de Inicio, y un archivo testigo previo en la carpeta de datos conserva su hash. [Evidencia de instalación](validation/installation-windows.json).

Esta prueba verifica instalación, versión y conservación del archivo testigo. No inicia el motor, no añade Mesa y no prueba audio. Complementa el arranque del motor descrito arriba; no equivale a validar una sesión de canto en un PC físico. El workflow se corrigió en main para que la ruta temporal de GitHub se resolviera en el contexto del paso; el instalador del tag publicado permaneció sin cambios.

## Actualización HiDPI posterior a v0.1.0

La actualización del renderer separa coordenadas lógicas y píxeles físicos, declara Retina en ambos bundles y rasteriza las fuentes según el viewport y la proyección de cada zona. El tamaño predeterminado sigue siendo 1280×800 puntos; `--window-size 1920x1080` permite solicitar una ventana mayor. El motor respeta el tamaño real si macOS la limita al espacio disponible. El recorte de la sílaba resaltada también usa el viewport del escenario para mantener alineadas ambas capas de la letra.

La [evidencia de pantalla](evidence/display-hidpi-macos.json) registra muestras estabilizadas del paquete, sin override del motor: 1280×800 lógico → 2560×1600 físico; petición 1920×1080 → 1512×831 lógico real → 3024×1662 físico en este monitor. Ambos casos conservan factor 2 en cada eje. Estas medidas verifican densidad y geometría; la revisión visual comprueba aparte la nitidez.

La [sesión integral HiDPI](evidence/session-hidpi-macos.json) repite las 17 comprobaciones con el paquete y PATH restringido. El [informe de empaquetado](validation/packaging-hidpi-macos.json) identifica el motor exacto, la firma ad hoc, las declaraciones Retina y las dependencias. Las pruebas siguen usando señales sintéticas, sin certificar micrófonos físicos.

La revisión visual de la app instalada comprueba canto y ajustes a 1000×640, biblioteca a 1280×800 y ampliación/restauración mediante el control nativo de macOS. La letra resaltada permanece alineada con su capa base. Se verifican selección de pestaña y campo con ratón, pegado de `canción española`, foco visible y regreso a la biblioteca. Capturas: `.impeccable/review/retina-singing-demo-1000.jpg`, `retina-settings-1000.jpg`, `retina-search-zoomed.jpg` y `retina-library-1280.jpg`. Los dos archivos SQLite existentes conservan sus hashes al sustituir la app; queda abierta en modo normal, sin entrada sintética.

Esta actualización se instala localmente en el Mac y su código está en main. Los archivos de la release v0.1.0 se conservan intactos; no representan esta compilación posterior.

Windows compila, empaqueta y supera el arranque/cierre del motor corregido en la [ejecución 43498190710](https://github.com/AlexAmMo/karaoke/actions/runs/43498190710), revisión `7515194`. El [informe de Windows](validation/display-windows-ci.json) registra una ventana 1280×800 y drawable 1280×800, factor 1 en ese runner, con Mesa llvmpipe y audio SDL dummy. Se verifica también el proveedor congelado. El cambio activa el soporte DPI de SDL en Windows; esta prueba por software no certifica un monitor Windows a escala 125/150/200%, ni audio físico.

## Repertorio reproducible

[REPERTORIO-VALIDACION.csv](REPERTORIO-VALIDACION.csv) contiene 40 candidatos únicos: 20 en inglés y 20 en español, incluyendo cuatro canciones de Eminem y rap en español. Es una selección de trabajo para la fase 1 del plan, no una medida de cobertura del catálogo. Los resultados del ensayo autenticado del 17 de noviembre figuran en cada fila. El estado `paquete_validado` registra preparación técnica; la escucha y la comprobación de sincronía se miden por separado.

El recorrido de validación para cada fila es el siguiente.

1. Buscar artista y título; registrar en `mapa_id` el identificador y la URL de la ficha elegida. Identificar la edición o grabación concreta antes de preparar sus medios.
2. Preparar la canción con voz original y comprobar la descarga automática, los recursos, las letras y el mapa. Revisar inicio, centro y final; un audio con el mismo título no acredita compatibilidad.
3. Cantar el mapa y comprobar notas, sincronización y puntuación. Para rap, anotar las partes que el mapa marca como libres y las que evalúa el motor.
4. Buscar una instrumental existente; registrar si es compatible, ambigua, incompatible o no localizada. Su ausencia no convierte en fallida una canción que funciona con voz original.
5. Anotar en `resultado` fecha, edición/enlace del medio, presencia de voz original, resultado de la preparación automática, revisión de instrumental, incidencias y referencia a la evidencia. Marcar `validado` solo después de una sesión real; usar `bloqueado` para problemas de acceso o recursos y `sin_mapa_en_USDB` únicamente tras una búsqueda completada sin coincidencias.

Los errores de autenticación o de conexión no cuentan como ausencia de mapas. Los resultados se resumirán por separado para cada idioma: canciones comprobadas sobre 20 y canciones listas sobre 20, acompañadas de los fallos observados. No se extrapolarán estos resultados a todas las canciones del catálogo.


## Interfaz clásica y panel plegable — 14 de noviembre de 2026

Runtime `6be1f3e`, paquete local de desarrollo (el release público v0.1.0 no se ha reemplazado). Interfaz basada en referencias PS3 clásicas: [investigación](research/SINGSTAR-REFERENCIAS.md). Biblioteca en carrusel con metadatos/portadas locales; lateral plegable y navegación por teclado; HUD propio sobre Deluxe. El escenario de canto conserva 4:3 y el render Retina sigue a escala física 2×.

- 65 pruebas Python superadas, incluidas navegación completa por biblioteca, selección estable, cola y portadas válidas/contenidas en el paquete.
- 20 comprobaciones integradas con motor final: [evidencia](evidence/session-ps3-macos.json), 33,08 s. Plegar continúa audio/puntuación/cola; desplegar restaura geometría; reiniciar vuelve a abrir el panel. Entrada sintética, no micrófono físico.
- Paquete congelado ejecutado con biblioteca de prueba separada: selección y cola por teclado, canto hasta resultados, ganador A4 y B4 fuera de tono. [Auditoría del paquete](validation/packaging-ps3-macos.json): firma ad hoc válida, 189 Mach-O, sin referencias absolutas a dependencias externas, ambos bundles con alta resolución habilitada.
- [Foco del teclado](evidence/ps3-keyboard-focus.json): desde el carrusel, Tab avanza al control de plegado y el foco se conserva al volver a abrir.
- CUA inspeccionó capturas a 1000×640, 1280×800 y ventana ampliada 1512×831. Los archivos incluyen la barra de título y están a 2×. Los gráficos y audio de demostración son originales y viven en datos de prueba; no se importaron a la biblioteca personal.
- Límite de automatización de ratón: SDL3 en macOS 26 consulta la posición global real, mientras los eventos sintéticos de CUA pueden conservar coordenadas anteriores. No se certifica clic físico a partir de esas pruebas. Se conserva el manejo estándar de eventos SDL, sin compensaciones específicas para la herramienta. Tampoco se certifican AX completo ni micrófono/latencia física.

La revisión visual independiente y su veredicto se registran en [ps3-finish-review.md](validation/ps3-finish-review.md).

La compilación final está instalada en `/Users/ton/Applications/Karaoke.app` y se ha abierto en modo normal a 1280×800. Motor SHA-256 `5c24b3c387ca64081e9aacf8859f2beb9a3a2e3a25f381a12fdf8c83da87105d`. Los dos archivos SQLite conservan sus hashes al sustituir el bundle. La copia previa a este rediseño se conserva en `build/before-ps3-install/Karaoke.app`; el paquete intermedio en `build/before-ps3-final-install/Karaoke.app`.

Windows supera compilación, empaquetado, arranque/cierre y proveedor congelado en la [ejecución 43534469382](https://github.com/AlexAmMo/karaoke/actions/runs/43534469382), mismo runtime `6be1f3e`. El [informe de Windows PS3](validation/display-ps3-windows-ci.json) registra 1280×800 a escala 1×, lateral abierto de 435 y escenario de 845. Usa Mesa llvmpipe y SDL dummy en una copia desechable de CI. No acredita aspecto visual, monitor HiDPI, hardware de audio ni una sesión completa de canto en Windows.

## Catálogo, carátulas y flecha del sistema · 17 de noviembre de 2026

Las mismas 40 consultas libres «artista título» pasaron de 0 coincidencias exactas con los filtros anteriores a 32 con el buscador actual, 20/20 en inglés y 12/20 en español. Se comparó la primera página y se exigió coincidencia normalizada de artista y título. El resultado anterior es específico de esa sintaxis: la búsqueda antigua con guion sí encontraba buena parte de la muestra. Se registraron los identificadores por canción. [Consultas antes y después](validation/catalog-queries.json)

Con cuenta real se descargó el audio asociado a una edición por título en un entorno temporal. 30/40 superaron el análisis técnico de mapa, duración, última nota y audio legible (19/20 en inglés y 11/20 en español). Para «Someone Like You» y «Rosas», el proveedor rechazó el recurso alternativo. Seis resultados de UltraStar España amplían el descubrimiento estricto a 38/40, con importación asistida. «Despacito» tiene una edición por comprobar y «Es épico» una petición documentada. La muestra de 40 no recibió escucha manual ni evaluación de sincronía durante canto. [Preparaciones por canción](validation/catalog-packages.json) · [Fuentes asistidas](validation/catalog-assisted.md)

Los dos paquetes opcionales se prepararon sin cuenta, con licencia íntegra y portada en la biblioteca después de limpiar la descarga temporal. «Northern Star» se reprodujo durante 190 segundos en Deluxe y llegó a resultados con 1720 puntos de entrada sintética. [Sesión de canto](validation/catalog-starter-session.json)

La suite integrada nativa de macOS superó 21 comprobaciones. Durante el canto, la consulta a SDL devolvió cursor visible con el panel abierto, plegado y reabierto, mientras continuaban audio, puntuación y cola. El reemplazo del bundle mantuvo tres IDs de biblioteca, preferencias y turnos. En el arranque normal las tres canciones existentes obtuvieron su carátula de USDB. Se inspeccionaron las vistas de biblioteca, búsqueda y panel plegado en Retina. La prueba física del puntero y micrófono queda pendiente. [Sesión con el motor actualizado](validation/catalog-ui-native-macos.json)

USDB invalida la sesión anterior de una cuenta cuando se autentica de nuevo. La app reutiliza una sesión efímera para búsquedas y preparaciones. En el ensayo real, dos búsquedas simultáneas encontraron sus mapas. Mientras se preparaba «Lose Yourself», otra búsqueda encontró «Dancing Queen» y el paquete terminó correctamente. [Prueba concurrente con cuenta real](validation/catalog-concurrent-search.json)

El paquete macOS arm64 de la revisión `6211f2c` pasó la verificación de firma y se instaló conservando los tres temas, cinco turnos, preferencias y acceso directo del escritorio. El paquete comprimido ocupa 192 MB y sus binarios requieren macOS 26. Al arrancar desde Finder, macOS solicitó de nuevo el permiso de micrófono asociado a esta compilación con firma ad hoc. Las pruebas de software suman 92 casos aprobados. [Auditoría del paquete instalado](validation/catalog-macos-package.json)

Windows x64 compiló y arrancó el paquete de la misma revisión. Durante canto con entrada sintética, el cursor SDL estuvo visible con el panel abierto, plegado y abierto de nuevo. La reproducción avanzó en los tres estados. El entorno de CI empleó gráficos por software y audio simulado. [Informe del cursor en Windows](validation/catalog-windows-ci.json) · [Ejecución en GitHub](https://github.com/AlexAmMo/karaoke/actions/runs/44180509776)

## Catálogo combinado y revisión de sincronía · 17 de noviembre de 2026

En una biblioteca vacía y sin cuenta, «Alex Ubago Sigo Aqui» abre una obra con fichas independientes de AllKaraoke y UltraStar España. «Y yo sigo aquí» de Paulina Rubio queda separada. Los índices cargados en esta prueba contienen 7.562 entradas de AllKaraoke, 18.254 parejas de artista/título del índice histórico de España y 2.552 fichas con metadatos utilizables de USDB.eu. Las cifras se solapan. La muestra histórica de 40 devuelve 38 coincidencias estrictas y una edición con invitado. [Búsqueda y muestra](validation/catalog-sigo-aqui.json)

Se obtuvo el audio que identifica el propio mapa de «Sigo aquí» (vídeo IA0uSub1xy4, 224,68 segundos) y se comprobó que contiene 414 eventos de nota. Tres ventanas de análisis acústico estimaron los desplazamientos +50 ms, −50 ms y −100 ms. La comparación usa la mezcla completa y representa una estimación de melodía por ventana. Aquella revisión de la app pedía escuchar tres frases antes de guardar la edición. El recorrido actual automatiza esa decisión. «Rosas» y «Someone Like You» también se prepararon con los audios indicados por sus respectivos mapas. [Identidad de cada grabación](validation/catalog-recording-review.json) · [Comparación acústica](validation/catalog-acoustic-check.json)

Se prepararon los 39 paquetes oficiales con licencia del repertorio inicial. Los medios y mapas se contrastaron con el manifiesto fijado por revisión y se decodificaron los audios completos. Las siete variantes instrumentales de la colección se verificaron por separado. [Informe por paquete](validation/catalog-official-packs.json)

La suite de este cambio pasó 110 pruebas. La instalación de macOS conservó tres canciones, cinco turnos y las preferencias. Desde la propia app instalada se buscó Álex Ubago, se seleccionó AllKaraoke y se llegó a la revisión de tres frases con el análisis acústico visible y el guardado pendiente de escucha. Dos regresiones sintéticas cubren tanto un desplazamiento global de 900 ms como un desplazamiento exclusivo del último tercio. [Verificación instalada](validation/catalogue-federated-macos.json) · [Pruebas acústicas](../tests/test_acoustic.py)

Se prepararon por separado la edición de «Despacito» con Daddy Yankee y el remix con Justin Bieber. La primera produjo una estimación acústica inconcluyente, y el remix superó el control de desfase grande. El índice de AllKaraoke contiene 5.732 fichas que declaran una sola pista vocal y al menos uno de los idiomas inglés o español. Esta medida describe metadatos, con la disponibilidad del medio y su sincronía pendientes para las grabaciones no ensayadas. [Detalle de ambas ediciones y cobertura](validation/catalogue-federated-extra.json)

El motor de la aplicación macOS empaquetada reprodujo además un turno completo de «Sigo Aquí» en una biblioteca temporal. Se observaron posiciones a 50, 100, 150 y 200 segundos, seguidas de un turno finalizado con puntuaciones persistidas. El micrófono de prueba generó tonos sintéticos y la salida de audio fue simulada. Durante esa prueba, la biblioteca de uso diario permaneció en la revisión de la edición.

El paquete Windows x64 compiló y superó la prueba del ejecutable congelado, arranque del motor, importación y canto sintético con el panel abierto, plegado y restaurado. En el primer intento la prueba emitió la orden de importar antes de confirmar la recepción de la ruta del fixture. El segundo intento esperó el estado visible y terminó correctamente con el mismo código de la aplicación. [Prueba final en Windows](https://github.com/AlexAmMo/karaoke/actions/runs/44188110442) · [Evidencia del paquete](validation/catalogue-federated-windows.json)

## Sesión simplificada y carátulas en la búsqueda

La búsqueda de «Álex Ubago Sigo Aquí» agrupa las fuentes en una fila con portada y botón **+**. En dos ventanas Retina (1000×640 y 1280×800 puntos) se comprobó que al escribir aparece el resultado y que llevar el foco al botón conserva la cola hasta pulsar Intro. Dos búsquedas con caché vacía obtuvieron la portada del álbum. Una tercera encontró un límite temporal del proveedor de imágenes y mostró las iniciales del artista. La preparación de una canción es independiente de la descarga de su imagen. [Verificación en macOS](validation/ux-macos.json)

Con biblioteca temporal y sin cuenta, una pulsación en **+** preparó la grabación de «Sigo Aquí» con voz y notas en 10,7 segundos. El proceso verifica la correspondencia de la grabación descargada con el mapa y comunica un error si la comparación no es concluyente. La experiencia de preparación reemplaza la escucha obligatoria documentada en pruebas anteriores. Los paquetes oficiales se verifican con su manifiesto. Los archivos originales de un paquete local se comprueban tal como los declara su mapa.

El paquete de macOS completó una sesión de dos canciones. Se recorrieron búsqueda durante el canto, pausa y reanudación, importación, cambios de cola, puntuaciones y reapertura. El motor pasó otras 21 comprobaciones con señal de micrófono sintética. Se comprobaron además las opciones para dos cantantes, la selección de entradas y la recuperación tras una descarga fallida. La latencia y el retorno de un micrófono físico siguen pendientes. [Recorrido completo](validation/ux-host-journey.json) · [Ajustes y recuperación](validation/host-session-secondary.md)

Para repetir el recorrido en macOS con una biblioteca temporal y comprobar además la portada remota de esta canción, ejecuta desde la raíz del repositorio:

```sh
uv run python scripts/test_host_journey.py --launcher "$HOME/Applications/Karaoke.app/Contents/MacOS/karaoke" --check-remote-cover --output build/ux-qa/online-session.json
```

El paquete x64 superó además la búsqueda desde el campo con los catálogos sin conexión, la adición a la cola, el inicio de una canción local y el plegado del panel durante el canto en Windows Server 2022 con gráficos y audio de prueba. La suite Python de esta revisión pasó 120 pruebas en el Mac. [Ejecución Windows](https://github.com/AlexAmMo/karaoke/actions/runs/44194552768) · [Resultados del paquete](validation/ux-windows.json)

## Descarga dentro de Karaoke · 18 de noviembre de 2026

La búsqueda escrita de Mulán y el enlace de UltraStar España muestran la edición «Todo un hombre haré de ti». La ventana integrada abre la ficha oficial y su identificación. Cerrar el selector antes de recibir un paquete deja la cola intacta. La descarga real de esa edición requiere una cuenta de UltraStar España y pares disponibles. [Prueba con la ficha real](validation/in-app-spanish-login.json)

Se verificó la recepción de torrent y ZIP y la cancelación a mitad de la descarga con el selector Qt real y un servidor de pruebas local. Un ensayo adicional transfirió un mapa y su grabación entre pares BitTorrent locales, verificó los bytes y confirmó la sincronía con el análisis acústico. También se ejercitaron los casos de otra canción, dos mapas ambiguos y ausencia de fuentes. El paquete de macOS pasó la comprobación del navegador integrado y del motor de transferencia, y la suite Python pasó 134 pruebas. [Resultados del paquete](validation/in-app-macos.json) · [Pruebas de transferencia](../tests/test_torrent_package.py)

En la instalación actualizada del Mac, escribir «Mulán, todo un hombre haré de ti» mostró una sola fila con **+** y «Elegir en UltraStar España». Se conservaron cuatro canciones, diez turnos y las preferencias. En una biblioteca temporal también se preparó «Sigo Aquí» de Álex Ubago mediante AllKaraoke y se reprodujo hasta la puntuación con un micrófono sintético. La primera petición de audio falló y el siguiente intento completó la sesión. [Evidencia de ambas búsquedas](validation/in-app-macos.json)

El paquete de Windows x64 cargó el navegador y el cliente BitTorrent integrados. También pasó el recorrido de búsqueda local, cola, canto y plegado del panel. [Prueba del ejecutable Windows](validation/in-app-windows.json) · [Ejecución en GitHub](https://github.com/AlexAmMo/karaoke/actions/runs/44205321249)

## Afinación en directo

La prueba usa una frase con un la prolongado. Inyecta audio PCM tres semitonos por encima, tres por debajo, silencio y un La afinado. Compara los píxeles de la pantalla con una captura de referencia. Una segunda pasada usa dos cantantes con desviaciones en direcciones opuestas.

En el paquete instalado de macOS pasaron las 17 comprobaciones de imagen y puntuación. En silencio se observó un hueco en el trazo y, al afinar, la barra de acierto apareció sobre la guía. También se comprobó el indicador durante la introducción, el final de la frase y la pausa. Las 21 comprobaciones de sesión pasaron con el lateral abierto y plegado y con el retorno del micrófono silenciado. Estas pruebas utilizaron micrófonos sintéticos. [Captura de la pantalla de canto](validation/afinacion-en-directo.png)

Puedes repetir la prueba con el comando siguiente. Las capturas y los resultados se guardan en el directorio de salida.

```sh
uv run python scripts/test_live_pitch.py --launcher "$HOME/Applications/Karaoke.app/Contents/MacOS/karaoke" --output build/live-pitch
```

El ejecutable de Windows x64 también superó la comparación de capturas con uno y dos cantantes en el entorno de gráficos por software. [Prueba del paquete en Windows](https://github.com/AlexAmMo/karaoke/actions/runs/44376959340)

## Mando web en la red local

Se leyó el QR de una captura de la pantalla nativa de Karaoke. Dos navegadores con sesiones distintas usaron esa invitación, buscaron canciones simultáneamente, añadieron turnos y compartieron los controles de reproducción. Pausar desde un móvil y reanudar o terminar desde el otro produjo el cambio en el motor Deluxe. Se comprobó también la entrada por código, la reconexión al recargar, la revocación de acceso y que repetir la misma petición tras perder una respuesta produce un solo turno.

Las búsquedas simultáneas de «Sigo Aquí» y «Todo un hombre haré de ti» devolvieron respectivamente una edición automática de AllKaraoke y una edición de UltraStar España que requiere elegir el paquete en el PC. Los móviles conservan búsquedas independientes incluso al cambiar de página en el ordenador.

El flujo de dos mandos puede repetirse en una biblioteca temporal con audio sintético.

```sh
uv run python scripts/test_remote_session.py --launcher "$HOME/Applications/Karaoke.app/Contents/MacOS/karaoke"
```

Safari en un iPhone 17 Pro simulado con iOS 26.2 y Chrome en un emulador Android entraron en la sesión por el enlace leído del QR y añadieron sendas canciones desde la biblioteca. Se verificaron doce combinaciones de vista y anchura entre 320 y 768 píxeles CSS. La suite local pasó 139 pruebas. La instalación del Mac preservó las cinco canciones, los once turnos y las preferencias existentes.

En Windows x64 también pasaron las pruebas de dos mandos contra el ejecutable empaquetado, de canto y de afinación en pantalla. [Ejecución y paquete de Windows](https://github.com/AlexAmMo/karaoke/actions/runs/44383741672)
