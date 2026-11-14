---
name: Karaoke
description: Escenario carmesí y selección fucsia inspirados en SingStar clásico de
  PS3, con panel operativo plegable.
colors:
  selection-fuchsia: '#b50e40'
  focus-pink: '#f7407a'
  tab-fuchsia: '#a30938'
  text-selection: '#990e38'
  stage-focus: '#ffe6ed'
  stage-upper: '#4d060e'
  stage-deep: '#0e0205'
  stage-lower: '#6b0911'
  panel-dark: '#1b0309'
  status-dark: '#26040b'
  control-dark: '#380614'
  control-hover: '#660b26'
  transport-dark: '#4d061a'
  divider: '#5e1429'
  slider-track: '#5c2636'
  text-light: '#f2f2ed'
  text-muted: '#d9b8c2'
  footer-light: '#faf2f5'
  footer-shade: '#998f96'
  footer-ink: '#330f1a'
  lyric-active: '#005c9e'
  lyric-ready: '#212e3b'
  lyric-next: '#525e6b'
  note-sung: '#26b5f4'
  note-guide: '#2396e0'
  lyrics-upper: '#f8f9fbf8'
  lyrics-lower: '#e4e9eef8'
  score-backing: '#0a121eac'
typography:
  display:
    fontFamily: Noto Sans
    fontSize: 40px
    fontWeight: 400
  headline:
    fontFamily: Noto Sans
    fontSize: 38px
    fontWeight: 400
  empty-title:
    fontFamily: Noto Sans
    fontSize: 34px
    fontWeight: 400
  panel-title:
    fontFamily: Noto Sans
    fontSize: 28px
    fontWeight: 400
  result-name:
    fontFamily: Noto Sans
    fontSize: 26px
    fontWeight: 400
  result-song:
    fontFamily: Noto Sans
    fontSize: 24px
    fontWeight: 400
  score:
    fontFamily: Noto Sans
    fontSize: 38px
    fontWeight: 400
  cover-artist:
    fontFamily: Noto Sans
    fontSize: 21px
    fontWeight: 400
  section:
    fontFamily: Noto Sans
    fontSize: 20px
    fontWeight: 400
  body:
    fontFamily: Noto Sans
    fontSize: 18px
    fontWeight: 400
  count:
    fontFamily: Noto Sans
    fontSize: 17px
    fontWeight: 400
  label:
    fontFamily: Noto Sans
    fontSize: 16px
    fontWeight: 400
  caption:
    fontFamily: Noto Sans
    fontSize: 15px
    fontWeight: 400
  cover-action:
    fontFamily: Noto Sans
    fontSize: 13px
    fontWeight: 400
rounded:
  square: 0px
spacing:
  row-gap: 8px
  control-inset: 16px
  heading-inset: 22px
  content-inset: 24px
  stage-inset: 48px
components:
  button:
    backgroundColor: '{colors.control-dark}'
    textColor: '{colors.text-light}'
    typography: '{typography.body}'
    rounded: '{rounded.square}'
    width: 368px
    height: 40px
  button-hover:
    backgroundColor: '{colors.control-hover}'
    textColor: '{colors.text-light}'
    typography: '{typography.body}'
    rounded: '{rounded.square}'
  button-description:
    backgroundColor: '{colors.control-dark}'
    textColor: '{colors.text-light}'
    typography: '{typography.body}'
    rounded: '{rounded.square}'
    width: 368px
    height: 64px
  button-stage:
    backgroundColor: '{colors.selection-fuchsia}'
    textColor: '{colors.text-light}'
    typography: '{typography.body}'
    rounded: '{rounded.square}'
    height: 48px
  input:
    backgroundColor: '{colors.control-dark}'
    textColor: '{colors.text-light}'
    typography: '{typography.body}'
    rounded: '{rounded.square}'
    width: 368px
    height: 74px
  navigation-selected:
    backgroundColor: '{colors.tab-fuchsia}'
    textColor: '{colors.text-light}'
    typography: '{typography.label}'
    rounded: '{rounded.square}'
    width: 92px
    height: 36px
  transport:
    backgroundColor: '{colors.transport-dark}'
    textColor: '{colors.text-light}'
    typography: '{typography.label}'
    rounded: '{rounded.square}'
    width: 180px
    height: 36px
  panel-restore:
    backgroundColor: '{colors.control-dark}'
    textColor: '{colors.text-light}'
    typography: '{typography.label}'
    rounded: '{rounded.square}'
    width: 154px
    height: 40px
  cover-caption:
    backgroundColor: '{colors.selection-fuchsia}'
    textColor: '{colors.text-light}'
    typography: '{typography.body}'
    rounded: '{rounded.square}'
    height: 96px
  slider-track:
    backgroundColor: '{colors.slider-track}'
    height: 8px
    width: 290px
  slider-fill:
    backgroundColor: '{colors.focus-pink}'
    height: 8px
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

**Creative North Star: "Una canción en el escenario carmesí"**

La identidad aprobada es una adaptación propia del SingStar clásico de PS3: escenario burdeos iluminado en carmesí, una portada protagonista con pie fucsia, vecinas subordinadas y un pie plateado. El lateral operativo usa la misma familia cálida con densidad controlada; se pliega para recuperar espacio de canto. La marca es Karaoke y los gráficos del HUD son originales.

Se documenta el artefacto nativo SDL/OpenGL, no una réplica histórica certificada. La elección explícita del usuario sustituye el sistema verde anterior; conserva la ventana única, la biblioteca y cola persistentes, el inicio manual de cada turno y el canto concurrente con la preparación. Las referencias históricas y sus límites están en `docs/research/SINGSTAR-REFERENCIAS.md`; la composición vigente está en `.impeccable/surfaces/native-ukaraokeshell-pas.md`.

**Key Characteristics:**

- Escenario burdeos con luz carmesí y selección fucsia.
- Una portada dominante, vecinas menores y reflejos subordinados.
- Texto regular claro, pie plateado y foco explícito de teclado.
- Panel operativo plegable y canto real de Deluxe en proporción 4:3.

Fuentes: `native/UKaraokeShell.pas`, `scripts/prepare_engine_theme.py`, `scripts/create_theme_assets.py`, `patches/deluxe-integration.patch` y `assets/theme/manifest.json`. La revisión visual y su alcance se registran en `docs/validation/ps3-finish-review.md`; la prueba de continuidad con entrada sintética en `docs/evidence/session-ps3-macos.json`. Las portadas, canciones y audio de las capturas de prueba son fixtures propios aislados, no repertorio distribuido. Windows físico, micrófonos físicos y semántica AX no quedan certificados por estas pruebas.

La revisión final declara `disposition: ship` sobre el runtime `6be1f3e`: recorrido de Tab tras flechas corregido y mensaje de resultados condicionado a la cola real. El cierre verifica esas correcciones sobre el alcance macOS Retina previo; no amplía las certificaciones de hardware, plataforma o accesibilidad.

## Colors

Burdeos casi negro, rojo luminoso y fucsia articulan navegación y selección; el canto cambia a cápsulas cian/rojas y banda clara. Los hex del frontmatter son representaciones portables calculadas como `floor(canal_normalizado × 255 + 0.5)`. Los valores fuente exactos se conservan como CSS RGB porcentual en `extensions.colorMeta.<token>.canonical` del sidecar; para volver al renderer, dividir cada porcentaje por 100. No son colores muestreados de capturas ni valores oficiales de Sony. Las entradas del generador PNG conservan sus canales RGBA de ocho bits.

### Primary

- **Fucsia de acción** (`selection-fuchsia`): pie de portada seleccionada, búsqueda vacía y regreso al repertorio.
- **Rosa de foco** (`focus-pink`): marco de foco del lateral, subrayado activo y volumen.
- **Fucsia de pestaña / selección de texto** (`tab-fuchsia`, `text-selection`): estados persistentes de navegación y edición.
- **Rosa pálido de escenario** (`stage-focus`): marco de foco de portada y acciones del escenario.

### Secondary

- **Cian cantado / azul guía** (`note-sung`, `note-guide`): geometría PNG propia de cápsulas, combinada con los colores de jugador del motor. No usar como sustitución del fucsia de navegación.
- **Azul de sílaba activa** (`lyric-active`): avance de letra sobre la banda clara; letra disponible y siguiente línea usan `lyric-ready` y `lyric-next`.

### Neutral

- **Burdeos de escenario** (`stage-upper`, `stage-deep`, `stage-lower`): extremos del degradado vertical y unión oscura.
- **Burdeos de panel / estado** (`panel-dark`, `status-dark`): zonas operativas fijas.
- **Control / hover / transporte** (`control-dark`, `control-hover`, `transport-dark`): superficies funcionales en reposo y bajo el puntero.
- **División / pista** (`divider`, `slider-track`): separación y recorrido de volumen.
- **Blanco suave / rosa secundario** (`text-light`, `text-muted`): texto principal y ayuda.
- **Plata clara / sombra de plata / tinta** (`footer-light`, `footer-shade`, `footer-ink`): pie del escenario.
- **Bandas de letra / puntuación** (`lyrics-upper`, `lyrics-lower`, `score-backing`): materiales translúcidos generados para el HUD.

**The State Before Ornament Rule.** El foco debe seguir identificable sobre la selección: marco rosa en el panel y pálido en el escenario, además del fondo de estado.

Las rampas OKLCH del sidecar son muestras derivadas para el panel de diseño, no nuevos colores implementados. Los tonos auxiliares de reflejo y fundas sin portada permanecen definidos en `CoverAt`; no forman una escala cromática general.

## Typography

**Display Font / Body Font:** Noto Sans, familia 0 del motor, estilo regular. `build/engine/game/fonts/fonts.ini` carga `GoNotoKurrent-Regular.ttf` y usa `GoNotoCurrent-Regular.ttf` como fallback de glifos. No se ha identificado ni incorporado una fuente propietaria de Sony.

Los tamaños `px` del frontmatter representan unidades solicitadas a `SetFontSize`, no píxeles físicos. El lateral escala su proyección de 400 unidades según el ancho disponible; el escenario usa coordenadas lógicas de ventana. No hay interlineado, tracking ni escala proporcional global declarados en el shell.

**The Logical Coordinates Rule.** Separar siempre unidades lógicas, proyección del panel, proyección 800×600 del canto y píxeles físicos al modificar geometría o revisar capturas.

### Hierarchy

- **Display / headline:** «Tu interpretación» y «Elige tu canción»; el estado vacío usa `empty-title`.
- **Panel-title / result-name / result-song / score:** cabecera lateral, cantante, canción y puntuación.
- **Cover-artist / body / cover-action:** artista, título y acción del pie de portada.
- **Section / label / caption / count:** cabeceras de sección, pestañas y campos, ayudas de fila y contador de canciones.
- El artista y título de una funda sin imagen escalan respectivamente con `S × 0.09` y `S × 0.065`; no son tamaños fijos de interfaz.
- El HUD configura nombres a 18, puntuación a 32 y tiempo a 14 en su proyección 800×600; las letras se ajustan dentro de sus bandas por el motor.

`LabelAt` recorta por ancho con `...`, retirando caracteres UTF-8 completos. Los campos mantienen el contenido completo para edición/almacenamiento. El pie usa texto breve: `DarkLabel` no implementa el mismo truncado y no debe heredarse como patrón para contenidos arbitrarios.

## Layout

Una ventana, escenario izquierdo y panel derecho plegable. El ancho expandido es `round(clamp(ScreenW × 0.34, 340, 440))`: 340 a 1000 de ventana y 435 a 1280. El lateral proyecta 400 unidades de ancho y `ScreenH × 400 / ExpandedSideWidth` de alto. Plegarlo reduce su ancho a cero, sin dejar un carril vacío, y muestra «Mostrar panel» en un control de 154×40, a 16 unidades de los bordes superior y derecho. Este control no muestra contador de turnos.

El canto mantiene 4:3: `W = min(ScreenW − SideWidth, round(ScreenH × 4/3))`, `H = min(ScreenH, round(W × 0.75))`, centrado en la región disponible. La selección y resultados ocupan toda la región izquierda. No estirar el HUD al ancho panorámico. El tamaño mínimo de ventana es 1000×640; las verificaciones usan además 1280×800 y la ampliación disponible del monitor. No hay breakpoint móvil.

En el escenario, los títulos comienzan en `(48,48)` y reservan 48 a cada lado. La portada central mide `S = min(280, W × 0.32, ScreenH × 0.38)`, se centra en X y comienza en `Y = max(156, ScreenH × 0.24)`. Las vecinas de primer y segundo grado miden 0.72S y 0.60S; se dibujan desde la más lejana a la central. El pie seleccionado añade 96 de alto; el pie plateado ocupa 36 de alto desde `ScreenH − 64`.

El panel sitúa cabecera en `(22,22)`, cuatro pestañas desde `(12,68)` con paso 96 y tamaño 92×36, contexto/transporte desde Y=116, y filas desde `174 − Scroll`. Alturas: 48 simple, 72 con descripción, 82 campo, 74 volumen. El fondo interior mide 368 de ancho y altura de fila menos 8. Solo se dibujan filas completas entre 168 y `Height − 98`; scroll y foco mantienen esa unidad de fila. La banda de estado ocupa las últimas 94 unidades.

### Densidad de pantalla

Retina conserva layout y eventos SDL en unidades lógicas. Viewport/scissor se convierten al drawable físico redondeando ambos bordes; las fuentes eligen rasterización según viewport y proyección, con resolución base mínima 128. Una ventana lógica 1280×800 a escala 2 usa 2560×1600 píxeles físicos sin duplicar el tamaño de los controles. El clipping de sílaba activa permanece dentro del viewport del canto.

## Elevation & Depth

La profundidad procede de tamaño, superposición, sombreado y reflejos; no de sombras de caja. El escenario encadena dos degradados verticales con unión oscura al 55% de su altura. El pie plateado tiene su propio degradado. Los controles laterales son planos.

Las portadas vecinas se dibujan al 75% de intensidad; sus texturas usan reflexión separada 5 unidades, altura relativa 0.30 y `ReflectionAlphaDiff = 0.65`. Las fundas tipográficas sin portada tienen un reflejo geométrico propio de 0.25S; el pie central proyecta una franja de 35 de alto. No imponer la antigua prohibición de degradados: forman parte de la identidad aprobada.

La selección del carrusel y el plegado cambian geometría inmediatamente. No hay interpolación, easing ni duración de carrusel implementados; el movimiento funcional de notas, letras y puntuación pertenece al motor. Las observaciones temporales del SingStar de referencia no certifican movimiento equivalente en Karaoke.

## Shapes

Panel, pestañas, filas, portadas y acciones del escenario usan esquinas cuadradas. Las cápsulas del canto tienen extremos circulares generados; no extender esa forma a los controles administrativos. El foco de fila deja un marco de tres unidades: fondo de foco `(13,Y−3,374,RowHeight−2)` frente al control `(16,Y,368,RowHeight−8)`. Pestañas: marco de dos unidades; transporte: tres; portada: cuatro. El radio de la ventana macOS pertenece al sistema operativo.

## Components

### Buttons

Acciones laterales de texto a la izquierda: 368×40 o 368×64 con descripción. El hover cambia a `control-hover`, foco añade `focus-pink`; no existe animación de pulsación ni color de peligro general. Las acciones principales del escenario usan `selection-fuchsia`, altura 48 y texto de 18. El control de plegado usa un chevrón vectorial, no un glifo tipográfico.

### Inputs / Fields

Etiqueta persistente de 16 y valor de 18 en dos líneas, dentro de 368×74. Vacío: «Clic para escribir». Edición al final mediante SDL, con `|` como cursor; selección total en rectángulo 350×29 desde `(22,Y+35)`. Cmd/Ctrl+A selecciona sin borrar; pegar o escribir sustituye la selección. Enter confirma, Escape descarta; contraseñas usan asteriscos. No documentar selección parcial ni cursor arbitrario como funciones disponibles.

### Navigation

Biblioteca, Buscar, Cola y Ajustes mantienen orden y posición. Activa: fucsia con línea inferior rosa de dos unidades. Cambiar página reinicia scroll; las actualizaciones de la misma página conservan foco por identificador de acción. Cmd/Ctrl+1–4 abre cada página y recupera el panel si estaba oculto.

### Carousel

Biblioteca real, con hasta cinco elementos visibles; flechas eligen y Enter sobre la selección añade a cola. Clic en portada central añade; clic en vecina selecciona. La portada ausente se representa con una funda tipográfica propia de artista/título, nunca con arte de álbum inventado. Biblioteca vacía conserva escenario y acción «Buscar canciones». No confundir selección con comienzo de canto: iniciar un turno sigue siendo explícito.

### Volume

Etiqueta de 18, pista 290×8, relleno proporcional y porcentaje de 16. Flechas ajustan cinco puntos dentro de 0–100. El volumen de música parte de 65%; el retorno de cada cantante parte de cero. El foco usa el marco de fila compartido.

### Panel, transport and status

Cmd/Ctrl+B o el control visible pliega/restaura el panel. Plegar suspende entrada SDL y conserva edición pendiente, foco por acción, cola, audio e interpretación; no envía ni descarta el texto. Durante canto, «Pausar / continuar» y «Terminar canción» miden 180×36. Cmd/Ctrl+P pausa; Cmd/Ctrl+E muestra el panel y pide terminar. Finalizar requiere confirmación.

El estado inferior muestra hasta cuatro líneas con paso 22, ancho de corte por palabras 350 y tamaño 16; los errores del motor tienen prioridad. Los mensajes extensos y palabras indivisibles siguen limitados por esa región: no convertir su recorte en una pauta de contenido. No comienza otra canción automáticamente.

### Singing HUD and results

`scripts/prepare_engine_theme.py` adapta el tema fijado de Deluxe de forma reproducible. Coordenadas del HUD 800×600: banda de letra `(0,484,800,94)`, primera línea `(38,492,724,34)`, siguiente `(38,539,724,28)`, tiempo `(0,578,800,22)` y progreso `(90,589,620,2)`. Puntuación de un cantante: fondo `(648,278,130,44)` y texto desde `(658,282)`; en dos cantantes la primera se sitúa a Y=98/102 y la segunda a Y=278/282. Cápsulas guía/cantadas y puntuaciones corresponden a la afinación real del motor; no son una simulación de interfaz.

Las texturas propias, licencia y hashes están en `assets/theme/manifest.json`; no incorporan imágenes de terceros. La paleta final de las notas combina esos mapas con los colores de jugador del motor; no inferir un color final único del PNG. El vídeo depende del paquete: una prueba sin vídeo puede tener escenario negro.

Resultados usa el escenario carmesí, hasta dos filas de 88 de alto con paso 108 y «Volver al repertorio». El pie distingue cola con turnos pendientes de cola vacía. Es adaptación propia, no una reconstrucción histórica certificada de SingStar.

### Keyboard and accessibility

Tab y Shift+Tab recorren escenario, plegado, pestañas y filas accionables; durante canto, escenario sale del recorrido y aparecen los dos controles de transporte. El recorrido envuelve y omite filas informativas. Con panel plegado, Tab alterna escenario/control de restauración entre canciones; durante canto enfoca restauración. Enter/Espacio activa el control; Espacio sin foco durante canto pausa. Después de flechas en el carrusel el foco sigue siendo el escenario, por lo que el siguiente Tab avanza al control de plegado.

SDL no expone actualmente semántica nativa completa para lectores de pantalla. Los previews HTML del sidecar son traducciones aisladas para revisar materiales y estados; sus botones, inputs y atributos accesibles no representan accesibilidad implementada en la app. No sustituyen la revisión nativa.

## Do's and Don'ts

### Do:

- **Do** mantener la portada elegida dominante y el foco visible sobre su estado de selección.
- **Do** conservar ventana única, panel recuperable y canto continuo al preparar otros turnos.
- **Do** usar contenido real de biblioteca y fundas tipográficas explícitas cuando falta portada.
- **Do** verificar teclado, acentos, textos largos y geometría en 1000×640, 1280×800 y Retina 2×.
- **Do** preservar proporción 4:3 y coordenadas propias del HUD al expandir el escenario.

### Don't:

- **Don't** restaurar el verde anterior ni prohibir los degradados y reflejos propios del mundo aprobado.
- **Don't** introducir inicio automático de turnos o una segunda ventana de canto en esta V1.
- **Don't** presentar fixtures de captura como canciones incluidas o sustituir afinación real por gráficos simulados.
- **Don't** atribuir a Sony los tokens, tipografía, panel lateral o resultados propios de Karaoke.
- **Don't** afirmar animación temporal del carrusel, validación física Windows/micrófonos o accesibilidad AX completa sin pruebas específicas.
