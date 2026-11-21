---
name: Karaoke
description: Escenario verde tinta, letra cálida y una cola compartida desde el ordenador y los móviles.
colors:
  stage: '#102321'
  panel: '#172c29'
  raised: '#243b37'
  line: '#425953'
  text: '#f7f4e9'
  muted: '#b7c8bf'
  accent: '#ffb18a'
  onAccent: '#332019'
  signal: '#acf1cd'
  guide: '#81968c'
  focus: '#ffe6a1'
  error: '#ffa9a1'
typography:
  stage:
    fontFamily: Instrument Sans
    fontSize: 36px
    fontWeight: 700
  heading:
    fontFamily: Instrument Sans
    fontSize: 24px
    fontWeight: 700
  song:
    fontFamily: Instrument Sans
    fontSize: 17px
    fontWeight: 600
  body:
    fontFamily: Instrument Sans
    fontSize: 16px
    fontWeight: 400
  caption:
    fontFamily: Instrument Sans
    fontSize: 14px
    fontWeight: 400
rounded:
  cover: 6px
  control: 8px
  sheet: 16px
spacing:
  step-4: 4px
  step-8: 8px
  step-12: 12px
  step-16: 16px
  step-24: 24px
  step-32: 32px
  step-48: 48px
---

# Diseño de Karaoke

El escenario concentra la atención en el próximo turno y en la letra durante el canto. La búsqueda y la cola comparten un lateral plegable. Los móviles gestionan la misma sala con una hoja para los detalles de cada canción o turno.

## Color y tipografía

La paleta vive en [session-palette.json](assets/theme/session-palette.json). `python3 scripts/create_theme_assets.py` genera los colores nativos, las variables CSS y las imágenes de notas, pausa y letra. El verde tinta sitúa el escenario detrás de la letra. El melocotón marca la acción principal y el presente musical. El contorno amarillo indica el foco. Cada estado cuenta también con texto o con una forma distinguible.

La aplicación distribuye Instrument Sans localmente. El PC carga regular y negrita. El mando usa el archivo variable WOFF2. Las carátulas se conservan en la misma posición aunque lleguen después de la búsqueda. Cuando faltan, la celda muestra iniciales sobre un color estable.

## Componentes

| Superficie | Presentación e interacción |
|---|---|
| Escenario vacío | Guía de notas ilustrada y acceso a Buscar. |
| Próximo turno | Portada o iniciales, título, intérprete, cantantes y acción de inicio. Las preparaciones pendientes llevan a su detalle. |
| Buscar | Campo por artista, título o vídeo y filtro «Solo descargadas». La fila muestra portada, título, artista y disponibilidad. Pulsar `+` crea un turno. Pulsar la fila abre sus ediciones y «Solo descargar». |
| Cola | Orden, participantes y preparación por turno. Los cambios llegan a los mandos. La preparación individual se consulta aquí aunque todavía no tenga turno. |
| Sesión | Volumen, afinación, cantantes y entradas. Los permisos del sistema y la selección de archivos se resuelven en el ordenador. |
| Mando | Dos destinos en la navegación inferior. Hoja inferior en anchos de hasta 420 px y diálogo centrado a partir de ahí. Los controles frecuentes tienen 44 px de superficie mínima. |

## Foco, movimiento y estados

Los controles confirman la adición con una marca en el mismo espacio. El mando aplica 120 ms de transición de color y respeta movimiento reducido. «Deshacer» se dirige al turno recién creado. Una búsqueda o una portada tardía conservan el foco de teclado por identidad de canción. Se puede plegar el panel con Cmd/Ctrl+B y recuperarlo desde «Mostrar panel».

Los resultados distinguen «Descargada», «Para descargar», «Preparando…», «Requiere al anfitrión», «Sin edición compatible» y «Copia incompleta». «Solo descargadas» se consulta en disco. La ficha detalla los pasos cuando la edición requiere intervención. El escenario inicia el canto al recibir una orden explícita.

Las medidas, criterios de contraste y pruebas de la dirección visual aparecen en el [sistema de sesión](docs/diseno/SISTEMA-DE-SESION.md).
