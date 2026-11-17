---
name: Karaoke
description: Biblioteca grafito con portadas, selección frambuesa y panel musical
  plegable.
colors:
  raspberry: '#a31447'
  focus-pink: '#f7407a'
  row-focus: '#fc91b8'
  add-focus: '#ffa8c7'
  stage-focus: '#ffb8d1'
  sleeve-selection: '#fa4d85'
  stage-graphite: '#141417'
  panel-graphite: '#1b1b1e'
  control-dark: '#27272c'
  control-hover: '#36363d'
  tab-selected: '#2e2930'
  transport-dark: '#302e33'
  status-dark: '#202024'
  add-background: '#382e38'
  divider: '#38383d'
  slider-track: '#47424a'
  text-selection: '#990e38'
  text-light: '#f7f5f7'
  text-muted: '#b8b8bf'
  initial-1: '#5c2e47'
  initial-2: '#304d5c'
  initial-3: '#38523d'
  initial-4: '#593d2e'
  initial-5: '#42385e'
  initial-6: '#5c3038'
  lyric-active: '#005c9e'
  lyric-ready: '#212e3b'
  lyric-next: '#525e6b'
  note-sung: '#26b5f4'
  note-guide: '#2396e0'
  lyrics-upper: '#f8f9fbf8'
  lyrics-lower: '#e4e9eef8'
  score-backing: '#0a121eac'
typography:
  score:
    fontFamily: Noto Sans
    fontSize: 42px
    fontWeight: 400
  headline:
    fontFamily: Noto Sans
    fontSize: 39px
    fontWeight: 400
  empty:
    fontFamily: Noto Sans
    fontSize: 36px
    fontWeight: 400
  results:
    fontFamily: Noto Sans
    fontSize: 34px
    fontWeight: 400
  library:
    fontFamily: Noto Sans
    fontSize: 30px
    fontWeight: 400
  panel:
    fontFamily: Noto Sans
    fontSize: 28px
    fontWeight: 400
  artist:
    fontFamily: Noto Sans
    fontSize: 22px
    fontWeight: 400
  section:
    fontFamily: Noto Sans
    fontSize: 20px
    fontWeight: 400
  body:
    fontFamily: Noto Sans
    fontSize: 18px
    fontWeight: 400
  action:
    fontFamily: Noto Sans
    fontSize: 17px
    fontWeight: 400
  label:
    fontFamily: Noto Sans
    fontSize: 16px
    fontWeight: 400
  caption:
    fontFamily: Noto Sans
    fontSize: 14px
    fontWeight: 400
rounded:
  square: 0px
spacing:
  stage-inset: 40px
  art-to-copy: 28px
  sleeve-gap: 12px
  row-inset: 16px
  thumb-to-copy: 12px
components:
  button:
    backgroundColor: '{colors.control-dark}'
    textColor: '{colors.text-light}'
    typography: '{typography.body}'
    rounded: '{rounded.square}'
    width: 368px
    height: 40px
  button-stage:
    backgroundColor: '{colors.raspberry}'
    textColor: '{colors.text-light}'
    typography: '{typography.action}'
    rounded: '{rounded.square}'
    width: 178px
    height: 44px
  input:
    backgroundColor: '{colors.control-dark}'
    textColor: '{colors.text-light}'
    typography: '{typography.body}'
    rounded: '{rounded.square}'
    width: 368px
    height: 66px
  navigation-selected:
    backgroundColor: '{colors.tab-selected}'
    textColor: '{colors.text-light}'
    typography: '{typography.label}'
    rounded: '{rounded.square}'
    width: 92px
    height: 36px
  panel-restore:
    backgroundColor: '{colors.control-dark}'
    textColor: '{colors.text-light}'
    typography: '{typography.label}'
    rounded: '{rounded.square}'
    width: 154px
    height: 40px
  song-row:
    backgroundColor: '{colors.panel-graphite}'
    textColor: '{colors.text-light}'
    typography: '{typography.body}'
    rounded: '{rounded.square}'
    width: 368px
    height: 60px
  song-add:
    backgroundColor: '{colors.add-background}'
    textColor: '{colors.text-light}'
    typography: '{typography.action}'
    rounded: '{rounded.square}'
    width: 38px
    height: 38px
  thumbnail:
    backgroundColor: '{colors.initial-1}'
    textColor: '{colors.text-light}'
    typography: '{typography.body}'
    rounded: '{rounded.square}'
    width: 48px
    height: 48px
  transport:
    backgroundColor: '{colors.transport-dark}'
    textColor: '{colors.text-light}'
    typography: '{typography.label}'
    rounded: '{rounded.square}'
    width: 180px
    height: 36px
  status:
    backgroundColor: '{colors.status-dark}'
    textColor: '{colors.text-light}'
    typography: '{typography.label}'
    rounded: '{rounded.square}'
    width: 399px
    height: 94px
---

# Design System: Karaoke

## Overview

**Creative North Star: "El disco tiene el escenario"**

La portada identifica la grabación antes de leer su título. En el escenario de grafito, la carátula y el nombre ocupan el centro de atención. A su derecha está la acción de añadir un turno. La tira inferior permite recorrer las canciones y el lateral reúne búsqueda, biblioteca, cola y ajustes.

**Key Characteristics:**

- Portada cuadrada con espacio propio y título contiguo.
- Fondo grafito continuo, texto claro y acción principal frambuesa.
- La misma imagen acompaña a la canción desde la búsqueda hasta la cola.
- El panel se pliega por completo para dar más espacio al canto.

## Colors

El escenario usa `stage-graphite`, el panel `panel-graphite` y el área de mensajes `status-dark`. Un separador de una unidad delimita la ventana lateral. El texto de título usa `text-light` y el artista y los metadatos usan `text-muted`. La acción principal usa `raspberry`; la tira de biblioteca señala la selección mediante `sleeve-selection`. Los marcos de teclado de la fila, el botón de añadir y la acción del escenario se documentan por separado. Los seis colores de iniciales proceden de la función nativa `Artwork`.

La banda de letras, las notas y el fondo de puntuación usan los recursos del tema de canto. Las cápsulas se componen con el color asignado a cada cantante por el motor. El frontmatter muestra equivalencias hexadecimales de ocho bits. El sidecar conserva los porcentajes RGB que recibe el renderer y rampas derivadas para el visor de diseño. [Tema](assets/theme/manifest.json)

## Typography

Noto Sans regular es la familia nativa del escenario y del panel. La cabecera de biblioteca mide 30 unidades. El título de canción usa el mínimo entre 39 y el ancho disponible dividido por 7,5, con salto entre palabras hasta dos líneas. El artista llega a 22. En una fila, el título mide 18 y la descripción 14. Las iniciales miden el 35 % del lado de su imagen. El tamaño lógico se conserva al dibujar sobre una superficie Retina.

## Layout

Una ventana de al menos 1000×640 puntos contiene escenario y lateral. El lateral ocupa el 34 % del ancho, entre 340 y 440 puntos. Dibuja sobre una proyección de 400 unidades de ancho. Al plegarlo, el escenario recupera su región completa y aparece «Mostrar panel» arriba a la derecha. Durante el canto, Deluxe centra el vídeo y la guía de afinación en un área proporcional 4:3.

En reposo, la portada protagonista comienza a 40 puntos del borde izquierdo. Su lado es el mínimo entre 396 puntos, el 45 % del ancho del escenario y el 42,5 % de la altura. Título, artista y botón forman una columna situada a 28 puntos de la portada. La tira inferior presenta hasta cinco miniaturas de hasta 78 puntos de lado, separadas por 12. La miniatura seleccionada lleva una línea de tres puntos cinco puntos por debajo de la imagen. Las flechas laterales de la tira aparecen cuando queda repertorio en esa dirección.

Las filas del panel comienzan a Y=118 en reposo o a Y=166 cuando hay transporte de reproducción o información del siguiente turno. Los mensajes de estado ocupan las últimas 94 unidades del panel. El sistema distingue las coordenadas lógicas de la ventana, la proyección lateral y los píxeles físicos.

## Elevation & Depth

La jerarquía nace de la escala de la portada, los espacios libres y la diferencia de luminosidad entre panel y escenario. El foco de teclado se dibuja alrededor de la acción correspondiente. En las filas informativas, una línea fina separa los títulos.

## Shapes

Portadas, miniaturas y controles son rectangulares, con esquinas cuadradas. Las flechas de navegación se dibujan con dos segmentos y la acción de encolar con dos trazos perpendiculares. Los contornos de foco de los botones del escenario y de las filas musicales tienen dos unidades de ancho.

## Components

**Portadas.** La misma ruta de imagen validada sirve para escenario, tira y lista. El renderer conserva hasta 32 texturas locales por uso reciente. Cuando falta una imagen, el nombre del artista determina un color y sus iniciales. Si falta el artista, el título determina el monograma. Si llega una portada después, se sustituye dentro del mismo espacio.

**Fila musical.** Cada fila ocupa 62 unidades. La miniatura mide 48×48 y el título y la descripción comienzan a X=82. Cuando la canción permite añadir turno, el botón tiene 38×38 unidades a X=340. El cuerpo abre el detalle cuando lo ofrece el servicio. Tab recorre el cuerpo y el botón como acciones independientes. Derecha o «+» en la fila añade el turno directamente. El lector conserva su posición mediante el identificador de la acción al actualizar resultados.

**Panel y campos.** Las cuatro pestañas de 92×36 permanecen arriba. La página activa conserva un subrayado rosa. Cmd/Ctrl+1–4 abre la sección elegida y Cmd/Ctrl+B pliega o despliega el panel. El campo muestra etiqueta y valor, y desplaza el texto editado para mantener visible el punto de escritura. Enter confirma, Escape descarta y Cmd/Ctrl+A selecciona el valor completo. Plegar conserva la edición pendiente y suspende la entrada de texto.

**Cursor.** El modo Karaoke mantiene la flecha nativa de SDL visible durante el canto y al recuperar el foco de la ventana. El campo de escritura dibuja su propio cursor de dos unidades. El estado del ratón, la canción seleccionada y el foco de teclado son independientes. [Prueba de sesión en macOS](docs/validation/catalog-ui-native-macos.json)

**Canto y resultados.** La partitura y las letras usan el lienzo lógico 800×600 de Deluxe. Música, micrófonos, letra y puntuación siguen activos al plegar el panel. Al finalizar, el escenario muestra el título de la canción, los nombres y sus puntuaciones alineadas a la derecha, con una acción para volver al repertorio. La biblioteca vacía presenta «Buscar canciones». El usuario inicia cada interpretación desde la cola.

## Do's and Don'ts

### Do:

- Conservar el foco y la selección al resolver imágenes o recibir más resultados.
- Mostrar la misma identidad visual para una canción en todas las superficies.
- Comprobar el panel con acentos, títulos largos y cambios de escala.
- Verificar que el puntero y los controles de canto siguen accesibles después de plegar.

### Don't:

- Evitar que una carátula tardía desplace la fila o cambie el turno activo.
- Evitar presentar el monograma como portada del disco.
- Evitar deformar el escenario de canto al aprovechar el ancho del panel.
