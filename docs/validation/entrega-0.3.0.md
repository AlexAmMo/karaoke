# Instalación y actualización de Karaoke 0.3.0

## Biblioteca de la versión anterior

Se tomó una instantánea de solo lectura de una biblioteca existente de la versión 0.2 y se abrió la copia con la versión nueva. Tras la migración de SQLite de 2 a 3, se compararon todas las columnas originales de canciones, turnos, ajustes y alias. Los valores coincidieron. Pasaron las comprobaciones de integridad y claves externas. La copia de recuperación conservó la versión 2 y los datos anteriores. Los archivos personales y sus contenidos quedaron fuera de las evidencias.

## Cerrar y volver a cantar

En macOS ARM64 se cerró la ventana con el botón rojo durante la canción y con Cmd+Q durante una pausa. El lanzador terminó con código 0 y la siguiente apertura devolvió el turno a la cola. El evento de teclado SDL para Ctrl+Q produjo el mismo resultado. El botón rojo y Cmd+Q se ejercieron con eventos de AppKit en una copia de pruebas. En otro ensayo se ordenó empezar y salir en el mismo ciclo de actualización. El turno se conservó y el motor dejó de ejecutar las órdenes posteriores al cierre. [Recorrido instalado](../../scripts/test_session.py)

## Calidad de las grabaciones

El catálogo verifica la edición antes de ponerla a cantar. En la prueba del generador se compararon 40 grabaciones completas con mapas humanos. El editor y la aprobación del anfitrión forman parte del flujo de generación. [Resultados por idioma](generacion-iteracion.md) · [Cobertura y descarga efectiva](catalogo-2026-11-21.md)

## Paquetes de escritorio

Los paquetes se construyeron desde `f73f563`. En Apple Silicon e Intel el instalador abrió el ZIP de su arquitectura y arrancó el motor incluido. En cada máquina se repitieron tres sesiones nuevas que cubrieron importar canciones, empezar el turno, cambiar la cola mientras sonaba el acompañamiento, cerrar y recuperar el turno. Se comprobó la señal Opus del teléfono y la conversión de audio por bloques. En Windows Server 2022 se comprobó el buscador y se cantó con fuentes sintéticas, se variaron las tolerancias de afinación y se gestionó la cola desde tres navegadores móviles. Las pruebas de gráficos en el runner Windows usan Mesa en una copia desechable. [Compilación y pruebas de los tres paquetes](https://github.com/AlexAmMo/karaoke/actions/runs/44908926828)
