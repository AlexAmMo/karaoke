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

## Repertorio reproducible

[REPERTORIO-VALIDACION.csv](REPERTORIO-VALIDACION.csv) contiene 40 candidatos únicos: 20 en inglés y 20 en español, incluyendo cuatro canciones de Eminem y rap en español. Es una selección de trabajo para la fase 1 del plan, no una medida de cobertura del catálogo. Todas las filas están `pendiente`; `mapa_id` y `resultado` permanecen vacíos porque todavía no se ha realizado la comprobación autenticada.

Cuando se disponga de acceso a USDB, se seguirá el mismo recorrido para cada fila:

1. Buscar artista y título; registrar en `mapa_id` el identificador y la URL de la ficha elegida. Identificar la edición o grabación concreta antes de preparar sus medios.
2. Preparar la canción con voz original y comprobar la descarga automática, los recursos, las letras y el mapa. Revisar inicio, centro y final; un audio con el mismo título no acredita compatibilidad.
3. Cantar el mapa y comprobar notas, sincronización y puntuación. Para rap, anotar las partes que el mapa marca como libres y las que evalúa el motor.
4. Buscar una instrumental existente; registrar si es compatible, ambigua, incompatible o no localizada. Su ausencia no convierte en fallida una canción que funciona con voz original.
5. Anotar en `resultado` fecha, edición/enlace del medio, presencia de voz original, resultado de la preparación automática, revisión de instrumental, incidencias y referencia a la evidencia. Marcar `validado` solo después de una sesión real; usar `bloqueado` para problemas de acceso o recursos y `sin_mapa_en_USDB` únicamente tras una búsqueda completada sin coincidencias.

Los errores de autenticación o de conexión no cuentan como ausencia de mapas. Los resultados se resumirán por separado para cada idioma: canciones comprobadas sobre 20 y canciones listas sobre 20, acompañadas de los fallos observados. No se extrapolarán estos resultados a todas las canciones del catálogo.
