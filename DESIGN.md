---
name: Karaoke
description: Una sesión doméstica tranquila, con el canto visible y los controles a mano.
colors:
  focus-sage: "rgb(53% 75% 66%)"
  selected-slate: "rgb(20% 29% 28%)"
  text-selection: "rgb(24% 38% 34%)"
  stage-dark: "rgb(4.5% 5.4% 6.1%)"
  sidebar-dark: "rgb(8.5% 10% 11%)"
  status-dark: "rgb(10% 13% 14%)"
  control-dark: "rgb(13% 16% 18%)"
  control-hover: "rgb(21% 26% 27%)"
  transport-dark: "rgb(18% 22% 24%)"
  divider: "rgb(22% 25% 27%)"
  slider-track: "rgb(27% 31% 32%)"
  text-light: "rgb(95% 95% 93%)"
  text-muted: "rgb(70% 74% 77%)"
typography:
  display:
    fontFamily: "Noto Sans"
    fontSize: "36px"
    fontWeight: 400
  headline:
    fontFamily: "Noto Sans"
    fontSize: "34px"
    fontWeight: 400
  score:
    fontFamily: "Noto Sans"
    fontSize: "30px"
    fontWeight: 400
  brand:
    fontFamily: "Noto Sans"
    fontSize: "28px"
    fontWeight: 400
  title:
    fontFamily: "Noto Sans"
    fontSize: "25px"
    fontWeight: 400
  result-body:
    fontFamily: "Noto Sans"
    fontSize: "24px"
    fontWeight: 400
  stage-lead:
    fontFamily: "Noto Sans"
    fontSize: "22px"
    fontWeight: 400
  stage-body:
    fontFamily: "Noto Sans"
    fontSize: "20px"
    fontWeight: 400
  body:
    fontFamily: "Noto Sans"
    fontSize: "18px"
    fontWeight: 400
  label:
    fontFamily: "Noto Sans"
    fontSize: "16px"
    fontWeight: 400
  caption:
    fontFamily: "Noto Sans"
    fontSize: "15px"
    fontWeight: 400
  scroll-cue:
    fontFamily: "Noto Sans"
    fontSize: "14px"
    fontWeight: 400
rounded:
  square: "0px"
spacing:
  row-gap: "8px"
  control-inset: "16px"
  heading-inset: "22px"
  content-inset: "24px"
  stage-inset: "48px"
components:
  button:
    backgroundColor: "{colors.control-dark}"
    textColor: "{colors.text-light}"
    typography: "{typography.body}"
    rounded: "{rounded.square}"
    width: "368px"
    height: "40px"
  button-hover:
    backgroundColor: "{colors.control-hover}"
    textColor: "{colors.text-light}"
  button-description:
    backgroundColor: "{colors.control-dark}"
    textColor: "{colors.text-light}"
    typography: "{typography.body}"
    rounded: "{rounded.square}"
    width: "368px"
    height: "64px"
  input:
    backgroundColor: "{colors.control-dark}"
    textColor: "{colors.text-light}"
    typography: "{typography.body}"
    rounded: "{rounded.square}"
    width: "368px"
    height: "74px"
  navigation-selected:
    backgroundColor: "{colors.selected-slate}"
    textColor: "{colors.text-light}"
    typography: "{typography.label}"
    rounded: "{rounded.square}"
    width: "92px"
    height: "36px"
  transport:
    backgroundColor: "{colors.transport-dark}"
    textColor: "{colors.text-light}"
    typography: "{typography.label}"
    rounded: "{rounded.square}"
    width: "180px"
    height: "36px"
  slider-track:
    backgroundColor: "{colors.slider-track}"
    rounded: "{rounded.square}"
    width: "290px"
    height: "8px"
  slider-fill:
    backgroundColor: "{colors.focus-sage}"
    rounded: "{rounded.square}"
    height: "8px"
  status:
    backgroundColor: "{colors.status-dark}"
    textColor: "{colors.text-muted}"
    typography: "{typography.label}"
    width: "399px"
    height: "94px"
---

# Design System: Karaoke

## Overview

**Creative North Star: "Una canción más"**

Una herramienta discreta para preparar una sesión de karaoke en casa, incluso con poca luz. La superficie de control utiliza fondos oscuros, texto claro, filas regulares y un verde apagado que identifica selección, foco y volumen. La personalidad procede de la calma y de la claridad de las acciones en español.

El canto conserva la representación real de UltraStar Deluxe: letras, notas, afinación, colores de cada cantante y puntuaciones. Su animación funcional y sus materiales pertenecen al motor; este documento registra el lateral y los estados de espera/resultados añadidos por Karaoke. No introduce una nueva apariencia para las barras de Deluxe ni animaciones decorativas.

**Key Characteristics:**

- Controles oscuros y planos, con un acento verde apagado.
- Jerarquía por tamaño, posición y tono; tipografía regular.
- Canto visible mientras se preparan los siguientes turnos.
- Estados y acciones explícitos en español, sin inicio automático del siguiente turno.

Fuente normativa de los valores: `native/UKaraokeShell.pas`; contenido y estados: `src/karaoke/service.py`. Familia tipográfica contrastada con `build/engine/game/fonts/fonts.ini` y `build/engine/src/base/UText.pas`. Evidencia visual: `.impeccable/review/session-final-1280.jpg`, `selection-1280.jpg` y `settings-1000.jpg`, capturas de macOS con entrada sintética. La revisión final comprobó el estado de canto, la selección de texto y los recorridos de teclado corregidos. `installed-first-run.jpg` registra el primer arranque de la app instalada, sin entradas sintéticas ni canciones. Windows no está verificado visualmente y no se ha validado la experiencia con micrófonos físicos.

## Colors

Grises oscuros ligeramente fríos, blancos suaves y un verde salvia moderado. Los valores RGB porcentuales del frontmatter preservan exactamente los canales normalizados del renderer; no son colores muestreados del JPEG. Las rampas OKLCH del sidecar son muestras derivadas para explorar el color en el panel, no tokens implementados ni autorización para añadir tonos al shell.

### Primary

- **Salvia de foco** (`focus-sage`): marco de foco y tramo rellenado de volumen.
- **Pizarra seleccionada** (`selected-slate`): fondo de la pestaña activa.
- **Verde de selección de texto** (`text-selection`): fondo del valor cuando se selecciona todo el campo.

### Neutral

- **Escenario oscuro** (`stage-dark`): espera y resultados a la izquierda.
- **Lateral oscuro** (`sidebar-dark`): base de la sesión.
- **Estado oscuro** (`status-dark`): banda fija inferior de mensajes.
- **Control oscuro / control señalado** (`control-dark`, `control-hover`): botones y campos; el segundo indica el puntero sobre una fila.
- **Transporte oscuro** (`transport-dark`): controles de interpretación.
- **División / pista** (`divider`, `slider-track`): separación entre regiones y recorrido de volumen.
- **Texto claro / secundario** (`text-light`, `text-muted`): etiquetas principales frente a ayuda, valores de campos y mensajes.

**The Functional Accent Rule.** El acento del lateral comunica selección, foco o volumen; no se utiliza como decoración ni sustituye los colores funcionales del canto de Deluxe.

## Typography

**Display Font / Body Font:** Noto Sans, familia 0 de Deluxe, estilo regular, sin cursiva. La distribución inspeccionada carga `GoNotoKurrent-Regular.ttf`, con `GoNotoCurrent-Regular.ttf` como fallback de glifos. No hay familia monoespaciada ni peso especial en el shell.

El tamaño en el frontmatter representa la altura solicitada a `SetFontSize`, expresada con `px` para intercambio del documento. En el lateral, **1 px del documento equivale a una unidad lógica SDL**, escalada por `SideWidth / 400`; no equivale a un píxel físico de una pantalla Retina. En espera/resultados se usa directamente el sistema de coordenadas de la ventana. No se prescribe una escala tipográfica proporcional ni un interlineado global inexistente.

### Hierarchy

- **Display / headline:** frase de bienvenida y título de resultados.
- **Score / brand / title:** puntuación, nombre Karaoke y cabecera «Tu sesión».
- **Result-body / stage-lead / stage-body:** canción y cantantes de resultados, orientación de espera.
- **Body:** etiquetas y valores de filas; aviso inferior del escenario.
- **Label:** pestañas, transporte, contador, porcentajes y mensajes.
- **Caption:** segunda línea descriptiva de una fila.
- **Scroll-cue:** indicadores de contenido fuera de la vista.

El texto de fila empieza en `(24, Y + 8)`; la segunda línea descriptiva en `Y + 36` y el valor de un campo en `Y + 40`. Las etiquetas largas se acortan por ancho con `...`, retirando caracteres UTF-8 completos. No presentar este recorte como ajuste automático en varias líneas.

## Layout

La composición de esta sesión está fijada en `.impeccable/surfaces/session.md`: escenario a la izquierda y lateral a la derecha, en una sola ventana. El lateral mide `round(clamp(ScreenW × 0.34, 340, 440))` unidades de ventana. A 1000 de ancho ocupa 340; a 1280 ocupa 435. Su proyección tiene ancho lógico 400 y alto `ScreenH × 400 / SideWidth`. No hay breakpoint móvil ni cambio a panel superpuesto.

El escenario de canto conserva proporción 4:3: `W = min(ScreenW − SideWidth, round(ScreenH × 4/3))`, `H = min(ScreenH, round(W × 0.75))`, centrado en la región izquierda. El fondo de espera y resultados ocupa toda esa región.

En coordenadas del lateral: cabecera en `(22, 22)`; cuatro pestañas desde `(12, 68)` con paso 96 y rectángulo 92 × 36; contexto o transporte desde `Y = 116`; filas desde `Y = 174 − Scroll`. Cada fila ocupa 48 unidades sin descripción, 72 con descripción, 82 para campo y 74 para volumen. Los fondos de controles miden el alto de fila menos 8. Solo se dibujan filas enteras dentro de los límites del área desplazable; el desplazamiento del ratón avanza por filas.

La banda de estado está anclada al fondo. El escenario usa margen lateral 48, ancho de texto `W − 96` y mantiene el aviso de preparación o prueba sintética cerca del borde inferior. Verificar la composición a 1280 × 800 y al mínimo acordado de 1000 × 640; estas medidas son tamaños de ventana de prueba, no resoluciones de archivo JPEG ni de framebuffer Retina.

## Elevation & Depth

El shell es plano: sin sombras, degradados, desenfoque ni elevación animada. Los distintos grises separan escenario, lateral, controles y estado. Una línea vertical de una unidad lógica divide las regiones. El marco verde identifica el foco; no representa elevación. Las barras brillantes y efectos de afinación visibles en el canto pertenecen a Deluxe y se conservan.

**The Quiet Controls Rule.** Los controles no añaden animación decorativa; el movimiento funcional del canto sigue siendo responsabilidad del motor.

## Shapes

Rectángulos de esquinas cuadradas, sin borde permanente en los controles. El radio del frontmatter es cero. El redondeo y los botones de la ventana macOS pertenecen al sistema operativo y no definen el estilo de las filas.

El foco de fila se dibuja detrás del control: rectángulo en `(13, Y − 3)`, ancho 374 y alto `RowHeight − 2`, frente al fondo interior en `(16, Y)`, ancho 368 y alto `RowHeight − 8`. Esto deja un marco visible de tres unidades lógicas. Las pestañas enfocadas tienen un marco de dos unidades (96 × 40 detrás de 92 × 36); el transporte usa tres (186 × 42 detrás de 180 × 36). Las barras de volumen son rectángulos de altura 8, sin tirador circular añadido.

## Components

### Buttons

Acciones de texto alineadas a la izquierda, con fondo oscuro y separación regular. El botón simple usa la fila sin descripción; una acción con ayuda usa la fila de dos líneas. Hover cambia el fondo al token `control-hover`; foco añade el marco salvia. No hay estilo destacado adicional para acciones primarias, animación de pulsación ni color de peligro definido. Las confirmaciones se expresan con contenido y acciones explícitas.

### Inputs / Fields

Etiqueta persistente arriba y valor secundario debajo, dentro de la misma superficie. Campo vacío muestra «Clic para escribir»; foco de edición añade `|` al final. Seleccionar todo preserva el valor y añade un fondo `text-selection` de 350 × 29 en `(22, Y + 35)`; escribir, pegar o borrar sustituye la selección. Contraseñas se ocultan con asteriscos. El marco verde es el mismo que en los botones; hover comparte el cambio tonal. Los textos visibles se recortan al ancho disponible; la edición y el almacenamiento no deben confundirse con ese recorte visual.

### Navigation

Biblioteca, Buscar, Cola y Ajustes mantienen orden y posición. La pestaña activa tiene fondo pizarra; no hay iconos ni navegación móvil alternativa. El contador de turnos queda a la derecha de «Tu sesión». Cambiar de página reinicia el desplazamiento; conserva el foco si ya estaba en una pestaña y descarta el foco de un control de la página anterior. Cuando una actualización asíncrona cambia las filas de la misma página, se conserva la acción enfocada por su identificador, no por su antiguo índice.

### Volume

Etiqueta, pista horizontal y porcentaje visible. El relleno mide `290 × valor / 100`; la pista parte de `(24, Y + 44)` y el porcentaje de `(325, Y + 36)`. El volumen de música parte de 65%; el retorno de cada cantante parte de cero. Foco usa el marco compartido, y las flechas ajustan el valor en pasos de cinco puntos, limitados a 0–100.

### Transport and status

Durante el canto aparecen «Pausar / continuar» y «Terminar canción» en dos rectángulos del mismo tamaño. Finalizar abre una confirmación en el lateral. La banda inferior muestra mensajes de servicio o error del motor, con prioridad para este último. El mensaje ocupa hasta cuatro líneas con paso 22, desde `(22, Height − 80)`, con ancho de texto 354 y corte por palabras a 350. No hay área de mensajes expandible: textos excesivos o palabras indivisibles aún pueden quedar recortados. Al recibir la confirmación del motor, «Preparando micrófonos e interpretación…» cambia a «Cantando. Puedes buscar y preparar los próximos turnos.»; ese cambio no sobrescribe otro mensaje posterior.

### Singing stage

Se reutilizan las letras, notas, afinación, tiempo y puntuaciones de Deluxe dentro de su viewport. Las vistas de espera y resultados propias utilizan texto regular y el fondo oscuro del shell. Los previews HTML del sidecar representan solamente controles del shell; no recrean ni sustituyen el canto.

### Keyboard and accessibility

Tab recorre las cuatro pestañas, los dos controles de transporte cuando se canta y las filas accionables; Shift + Tab invierte el recorrido. Ambos envuelven al llegar al extremo y omiten filas informativas. El foco de fila fuera de vista ajusta el desplazamiento para mostrarla entera. Enter o Espacio activan la pestaña, botón o transporte enfocados; Enter sobre volumen conserva el valor y las flechas lo ajustan.

Los campos reciben entrada de texto SDL; Enter confirma y Escape descarta la edición. Cmd/Ctrl + A selecciona el valor completo sin borrarlo; Cmd/Ctrl + V pega, sustituyendo la selección si existe. Cmd/Ctrl + 1–4 abre las páginas; durante el canto, Cmd/Ctrl + P pausa/continúa y Cmd/Ctrl + E abre la confirmación para terminar. Espacio sin foco pausa el canto. No inferir edición completa de texto, posición arbitraria del cursor o selección parcial: el editor SDL actual trabaja al final del valor.

La representación SDL no expone actualmente semántica nativa a lectores de pantalla. El marcado semántico de los previews HTML del sidecar es únicamente una ayuda para revisar los componentes y no constituye accesibilidad implementada en la aplicación. No afirmar cumplimiento completo por tener contraste o navegación de teclado.

## Do's and Don'ts

### Do:

- **Do** reutilizar las filas y los tokens existentes al añadir controles al lateral.
- **Do** mantener visible el canto al buscar, preparar turnos y abrir ajustes.
- **Do** distinguir unidades lógicas SDL, tamaño de ventana y píxeles físicos al revisar capturas.
- **Do** verificar foco, texto largo y mensajes en los dos tamaños de ventana acordados.
- **Do** conservar las barras, colores de jugador y animación funcional reales de Deluxe.

### Don't:

- **Don't** añadir animación decorativa, sombras o superficies luminosas al shell.
- **Don't** introducir una segunda ventana o una vista móvil/TV dentro de esta composición V1.
- **Don't** reemplazar las barras del motor con una simulación visual.
- **Don't** afirmar compatibilidad instrumental, validación con micrófono o accesibilidad completa a partir de una captura sintética.
