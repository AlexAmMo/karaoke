# Validación de la implementación

Estado inicial del 13 de noviembre de 2026. Este documento distingue código implementado, pruebas de software y comprobaciones que requieren equipos o cuentas externos.

## Comprobado localmente

- Compilación de Deluxe modificado en macOS Apple Silicon y verificación de firma ad hoc.
- Biblioteca/cola SQLite, alias de fuentes, deduplicación, staging, validación de recursos, recuperación de trabajos y turnos.
- 46 pruebas automatizadas del backend correctas. Incluyen procesamiento real TXT/SQLite/FFmpeg/Syncer con fronteras remotas sustituidas por datos de prueba. No simulan el resultado de todos los componentes.
- Error de autenticación USDB explícito desde el proceso real del adaptador, sin credenciales; no se confunde con catálogo vacío.
- Navegación de biblioteca, selección, añadir turno e inicio desde teclado en la app real.
- Canto con dos señales sintéticas: resultado 10.000 frente a 0. Escribir espacios y pegar `canción española` en el campo enfocado conserva el canto y los acentos.
- Inspección visual a 1280×800 y 1000×640. Las capturas están en `.impeccable/review/`.
- Cierre de la ventana mediante el atajo de sistema sin una confirmación oculta del menú anterior.

La automatización CUA de ratón entregó coordenadas SDL obsoletas respecto a su indicador visual. Se observó selección real de una fila mediante el ratón, pero esta evidencia no certifica todos los objetivos de clic. No se cambió el cálculo de coordenadas basándose en esa inyección inconsistente.

## Pendiente antes de declarar una V1 estable

- Micrófono por cable real, dos dispositivos/canales, niveles, retorno audible, latencia, realimentación y sincronía durante una sesión prolongada. El usuario todavía no dispone del micrófono.
- Descarga autenticada de canciones reales de USDB, prueba de enlaces y revisión musical de instrumentales. No se ha usado ni inventado una cuenta del usuario.
- Ejecución y prueba física en Windows; los resultados de CI se registrarán por separado.
- Instalación en máquinas limpias y comportamiento de Gatekeeper/SmartScreen. La firma local ad hoc no es una notarización de Apple ni firma comercial de Windows.
- La compilación local utiliza bibliotecas que requieren macOS 26. No demuestra compatibilidad con versiones anteriores. Los paquetes de CI deben declarar su mínimo efectivo a partir de su propio inventario.
- La interfaz SDL no expone semántica completa a lectores de pantalla. Tiene foco y operación por teclado, pero no se declara accesibilidad total.

La generación de mapas por IA, móviles, dúos con partes diferentes y segunda pantalla siguen fuera de V1. Los mapas de tiempos relativos requieren conversión previa; se rechazan con explicación. Si Syncer necesita escoger un audio alternativo ambiguo de comentarios, se rechaza y se pide otra fuente/importación compatible.
