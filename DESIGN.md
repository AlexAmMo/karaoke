---
name: Karaoke
description: Biblioteca grafito con portadas, selección frambuesa y panel musical
  plegable.
colors:
  raspberry: '#ab174f'
  focus-pink: '#fca8c7'
  row-focus: '#fca8c7'
  add-focus: '#fca8c7'
  stage-focus: '#fca8c7'
  sleeve-selection: '#fa4d85'
  stage-graphite: '#13141a'
  panel-graphite: '#1b1d24'
  control-dark: '#2e3038'
  control-hover: '#30333b'
  tab-selected: '#423442'
  transport-dark: '#3b303d'
  status-dark: '#1b1d24'
  add-background: '#382e38'
  divider: '#383b42'
  slider-track: '#454752'
  text-selection: '#990e38'
  text-light: '#f7f5f7'
  text-muted: '#babfc9'
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
    fontSize: 40px
    fontWeight: 700
  headline:
    fontFamily: Noto Sans
    fontSize: 45px
    fontWeight: 700
  empty:
    fontFamily: Noto Sans
    fontSize: 36px
    fontWeight: 700
  results:
    fontFamily: Noto Sans
    fontSize: 34px
    fontWeight: 400
  library:
    fontFamily: Noto Sans
    fontSize: 18px
    fontWeight: 400
  panel:
    fontFamily: Noto Sans
    fontSize: 22px
    fontWeight: 400
  artist:
    fontFamily: Noto Sans
    fontSize: 20px
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
  control: 6px
  tab: 7px
  add: 20px
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
    rounded: '{rounded.control}'
    width: 368px
    height: 40px
  button-stage:
    backgroundColor: '{colors.raspberry}'
    textColor: '{colors.text-light}'
    typography: '{typography.action}'
    rounded: '{rounded.tab}'
    width: 178px
    height: 44px
  input:
    backgroundColor: '{colors.control-dark}'
    textColor: '{colors.text-light}'
    typography: '{typography.body}'
    rounded: '{rounded.control}'
    width: 368px
    height: 44px
  navigation-selected:
    backgroundColor: '{colors.tab-selected}'
    textColor: '{colors.text-light}'
    typography: '{typography.label}'
    rounded: '{rounded.tab}'
    width: 92px
    height: 36px
  panel-restore:
    backgroundColor: '{colors.control-dark}'
    textColor: '{colors.text-light}'
    typography: '{typography.label}'
    rounded: '{rounded.control}'
    width: 148px
    height: 40px
  song-row:
    backgroundColor: '{colors.panel-graphite}'
    textColor: '{colors.text-light}'
    typography: '{typography.body}'
    rounded: '{rounded.control}'
    width: 368px
    height: 56px
  song-add:
    backgroundColor: '{colors.add-background}'
    textColor: '{colors.text-light}'
    typography: '{typography.action}'
    rounded: '{rounded.add}'
    width: 43px
    height: 43px
  thumbnail:
    backgroundColor: '{colors.initial-1}'
    textColor: '{colors.text-light}'
    typography: '{typography.body}'
    rounded: '{rounded.square}'
    width: 46px
    height: 46px
  transport:
    backgroundColor: '{colors.transport-dark}'
    textColor: '{colors.text-light}'
    typography: '{typography.label}'
    rounded: '{rounded.control}'
    width: 178px
    height: 36px
  status:
    backgroundColor: '{colors.status-dark}'
    textColor: '{colors.text-light}'
    typography: '{typography.label}'
    rounded: '{rounded.square}'
    width: 399px
---

# Diseño de Karaoke

Esta referencia corresponde a la aplicación 0.2. El [sistema visual de la próxima iteración](docs/diseno/SISTEMA-DE-SESION.md) incluye la maqueta de Buscar y Cola.

## Escenario

La portada y el título identifican la grabación seleccionada. «Añadir a la cola» incorpora un turno. La tira inferior reúne hasta cinco carátulas y mantiene una línea frambuesa bajo la elegida. Al comenzar con el repertorio vacío, una pequeña secuencia de notas acompaña la instrucción de añadir la primera canción. La búsqueda ya abierta recibe el foco de escritura.

El título del tema utiliza Noto Sans en negrita y admite dos líneas. Artistas, recuentos y mensajes tienen menor contraste. Cuando falta la portada, las iniciales sobre un color estable identifican al artista. La misma imagen acompaña al tema en la lista, el escenario y la cola.

## Panel

La ventana reparte el espacio entre escenario y panel. El panel mide entre 340 y 440 puntos y dibuja en una proyección de 400 unidades. Una sola banda superior reúne Biblioteca, Buscar, Cola, Ajustes y el control de plegado. El recuento de turnos aparece junto a Cola cuando hay alguno. El contenido se desplaza dentro del área entre navegación y mensajes. La altura del pie depende del mensaje activo.

La búsqueda acepta artista, título o enlace de YouTube. Tras 350 ms de pausa al escribir, el campo envía el texto. Los resultados muestran título, artista, una portada de 46 unidades y un control de añadir de 43 unidades. Al escoger una canción, la aplicación resuelve las ediciones compatibles en segundo plano. La importación, las fuentes y la cuenta se consultan desde sus secciones.

## Controles y teclado

El foco de teclado tiene un borde de una unidad. Las pestañas y acciones principales usan superficies redondeadas y la lista comparte el fondo del panel. Tab y Mayús+Tab recorren las acciones. En una fila musical, Derecha enfoca el signo de suma. Intro o Espacio confirma la adición. En un campo, Cmd/Ctrl+A selecciona el texto y Cmd/Ctrl+V pega. El buscador mantiene el foco después de recibir nuevos resultados.

Cmd/Ctrl+1–4 abre cada sección. Cmd/Ctrl+B pliega el panel. El escenario recupera el ancho disponible y «Mostrar panel» permite volver con ratón o teclado.

## Canto y puntuación

Deluxe conserva la proporción 4:3 para la letra y las notas durante el canto. El panel ofrece «Pausar» o «Reanudar» según el estado de la interpretación. Al acabar, el escenario presenta el tema, el artista, el nombre y los puntos de cada cantante, junto al próximo turno cuando existe. [Tema de canto](assets/theme/manifest.json)
