# Validación de la implementación

Estado inicial del 13 de noviembre de 2026. Este documento distingue código implementado, pruebas de software y comprobaciones que requieren equipos o cuentas externos.

## Comprobado localmente

- Compilación de Deluxe modificado en macOS Apple Silicon y verificación de firma ad hoc.
- Biblioteca/cola SQLite, alias de fuentes, deduplicación, staging, validación de recursos, recuperación de trabajos y turnos.
- 50 pruebas automatizadas del backend correctas. Incluyen procesamiento real TXT/SQLite/FFmpeg/Syncer con fronteras remotas sustituidas por datos de prueba. No simulan el resultado de todos los componentes.
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
- Ejecución y prueba física en Windows; los resultados de CI se registrarán por separado.
- Instalación en máquinas limpias y comportamiento de Gatekeeper/SmartScreen. La firma local ad hoc no es una notarización de Apple ni firma comercial de Windows.
- La compilación local utiliza bibliotecas que requieren macOS 26. No demuestra compatibilidad con versiones anteriores. Los paquetes de CI deben declarar su mínimo efectivo a partir de su propio inventario.
- La interfaz SDL no expone semántica completa a lectores de pantalla. Tiene foco y operación por teclado, pero no se declara accesibilidad total.

La generación de mapas por IA, móviles, dúos con partes diferentes y segunda pantalla siguen fuera de V1. Los mapas de tiempos relativos requieren conversión previa; se rechazan con explicación. Si Syncer necesita escoger un audio alternativo ambiguo de comentarios, se rechaza y se pide otra fuente/importación compatible.

## Revisión de interfaz

El revisor independiente de Impeccable resolvió cuatro defectos: Enter ya no cambia un slider, seleccionar todo conserva el texto, Tab/Shift+Tab recorren pestañas/transporte/controles y el mensaje de preparación cambia a canto al confirmarlo el motor. La segunda revisión dio `ship` para esos cuatro hallazgos y el alcance visual revisado; no certifica Windows, hardware ni lectores de pantalla. Capturas finales: `.impeccable/review/session-final-1280.jpg` y `selection-1280.jpg`.

## Paquete autónomo de macOS

La aplicación congelada completó de nuevo las 17/17 comprobaciones con `PATH=/usr/bin:/bin`, sin depender de Homebrew para ejecutar medios o el motor. Evidencia: `docs/evidence/session-frozen-macos.json` (33,14 segundos, 371 muestras). El controlador de pruebas se ejecuta con Python de desarrollo; la app, el motor y sus dependencias son los del paquete.

La revisión `5022719` pasa las 50 pruebas Python en GitHub Actions sobre Ubuntu y Windows Server 2022; también pasan localmente en macOS. Este resultado no equivale a probar el audio físico ni el renderizado Windows.

## Instalación en el Mac de desarrollo

Copiada a `~/Applications/Karaoke.app` y abierta mediante el mecanismo normal de lanzamiento de aplicaciones. Biblioteca inicial vacía, modo sintético desactivado. El selector nativo de carpetas abre y permite cancelar sin importar contenido. La app queda abierta para el usuario. Esta prueba no es una instalación en un Mac limpio y no verifica la política de cuarentena de una descarga nueva de navegador.
